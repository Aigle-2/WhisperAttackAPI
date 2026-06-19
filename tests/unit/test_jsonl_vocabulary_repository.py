"""Tests for the JSONL vocabulary repository adapter (ADR-0004).

Exercises the source/usage split, the join on ``id``, hot usage stamping, additive
seeding, eviction write-back, and graceful degradation — all against a tmp data dir so
nothing touches the real per-user directory.
"""

from __future__ import annotations

import json
from datetime import datetime

from vaivox.application.ports import VocabularyRepository
from vaivox.domain.vocabulary.governor import VocabularyGovernor
from vaivox.domain.vocabulary.model import (
    EvictionPolicy,
    VocabularyEntry,
    VocabularyKind,
    VocabularyOrigin,
)
from vaivox.infrastructure.vocabulary.jsonl_repository import JsonlVocabularyRepository

_KIND = VocabularyKind.FUZZY_WORD
_NOW = datetime(2026, 6, 18, 12, 0, 0)


def _entry(entry_id: str, origin: VocabularyOrigin = VocabularyOrigin.LEARNED) -> VocabularyEntry:
    return VocabularyEntry(id=entry_id, kind=_KIND, term=entry_id, origin=origin)


def test_repo_conforms_to_port(tmp_path) -> None:
    repo: VocabularyRepository = JsonlVocabularyRepository(str(tmp_path))
    assert isinstance(repo, VocabularyRepository)


def test_load_missing_files_returns_empty(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    assert repo.load(_KIND) == []


def test_add_then_load_round_trips(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(
        VocabularyEntry(
            id="m1",
            kind=_KIND,
            term="bogey dope",
            aliases=("bogie dope", "bandit dope"),
            origin=VocabularyOrigin.DEFAULT,
        ),
        _NOW,
    )

    loaded = repo.load(_KIND)

    assert len(loaded) == 1
    governed = loaded[0]
    assert governed.entry.id == "m1"
    assert governed.entry.term == "bogey dope"
    assert governed.entry.aliases == ("bogie dope", "bandit dope")
    assert governed.entry.origin is VocabularyOrigin.DEFAULT
    # Add seeds usage at the creation time (grace-window protection), zero hits.
    assert governed.usage.last_used == _NOW
    assert governed.usage.hits == 0


def test_add_is_idempotent_on_duplicate_id(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(_entry("dup"), _NOW)
    repo.add(_entry("dup"), _NOW)

    assert len(repo.load(_KIND)) == 1


def test_add_merges_word_mapping_aliases_for_existing_default(tmp_path) -> None:
    defaults = tmp_path / "defaults"
    data = tmp_path / "data"
    defaults.mkdir()
    data.mkdir()
    (defaults / "word_mapping.jsonl").write_text(
        json.dumps(
            {
                "id": "enter",
                "term": "Enter",
                "aliases": ["inter"],
                "origin": "default",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    repo = JsonlVocabularyRepository(str(data), default_source_dir=str(defaults))

    repo.add(
        VocabularyEntry(
            id="enter",
            kind=VocabularyKind.WORD_MAPPING,
            term="Enter",
            aliases=("inner",),
        ),
        _NOW,
    )

    governed = repo.load(VocabularyKind.WORD_MAPPING)[0]
    assert governed.entry.aliases == ("inner", "inter")
    assert (data / "word_mapping.jsonl").is_file()


def test_mark_used_stamps_recency_and_hits(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(_entry("a"), datetime(2026, 1, 1))
    repo.add(_entry("b"), datetime(2026, 1, 1))

    repo.mark_used(["a"], _NOW)

    by_id = {g.id: g for g in repo.load(_KIND)}
    assert by_id["a"].usage.hits == 1
    assert by_id["a"].usage.last_used == _NOW
    # The uncredited entry is untouched.
    assert by_id["b"].usage.hits == 0
    assert by_id["b"].usage.last_used == datetime(2026, 1, 1)


def test_mark_used_accumulates_hits(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(_entry("a"), datetime(2026, 1, 1))

    repo.mark_used(["a"], datetime(2026, 2, 1))
    repo.mark_used(["a"], _NOW)

    governed = repo.load(_KIND)[0]
    assert governed.usage.hits == 2
    assert governed.usage.last_used == _NOW


def test_mark_used_ignores_unknown_ids(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(_entry("a"), datetime(2026, 1, 1))

    repo.mark_used(["ghost"], _NOW)  # must not raise or create rows

    assert repo.load(_KIND)[0].usage.hits == 0


def test_source_never_stores_usage(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(_entry("a"), _NOW)
    repo.mark_used(["a"], _NOW)

    source_text = (tmp_path / "fuzzy_word.jsonl").read_text(encoding="utf-8")
    record = json.loads(source_text.strip())

    # ADR-0004 Option A: curated source stays free of hot usage fields.
    assert set(record) == {"id", "term", "aliases", "origin"}
    assert (tmp_path / "fuzzy_word.usage.json").is_file()


def test_replace_entries_drops_evicted_source_and_usage(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(_entry("keep"), datetime(2026, 1, 1))
    repo.add(_entry("drop"), datetime(2026, 1, 1))
    repo.mark_used(["keep"], _NOW)
    repo.mark_used(["drop"], _NOW)

    kept = [g for g in repo.load(_KIND) if g.id == "keep"]
    repo.replace_entries(_KIND, kept)

    loaded = repo.load(_KIND)
    assert [g.id for g in loaded] == ["keep"]
    # The evicted entry leaves no orphan usage row behind.
    usage = json.loads((tmp_path / "fuzzy_word.usage.json").read_text(encoding="utf-8"))
    assert set(usage) == {"keep"}


def test_governor_and_repo_integrate_for_eviction(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    governor = VocabularyGovernor()
    repo.add(_entry("fresh"), _NOW)
    repo.add(_entry("stale"), datetime(2020, 1, 1))

    result = governor.govern(repo.load(_KIND), EvictionPolicy(max_entries=1), _NOW)
    repo.replace_entries(_KIND, result.kept)

    assert [g.id for g in repo.load(_KIND)] == ["fresh"]
    assert result.evicted_ids == ("stale",)


def test_load_skips_malformed_source_lines(tmp_path) -> None:
    source = tmp_path / "fuzzy_word.jsonl"
    good = json.dumps({"id": "ok", "term": "Texaco", "aliases": [], "origin": "default"})
    source.write_text(
        f"{good}\nnot-json\n{{}}\n" + json.dumps({"id": "noterm"}) + "\n",
        encoding="utf-8",
    )

    loaded = JsonlVocabularyRepository(str(tmp_path)).load(_KIND)

    assert [g.id for g in loaded] == ["ok"]


def test_load_with_corrupt_usage_sidecar_degrades(tmp_path) -> None:
    source = tmp_path / "fuzzy_word.jsonl"
    source.write_text(
        json.dumps({"id": "a", "term": "Texaco", "aliases": [], "origin": "learned"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "fuzzy_word.usage.json").write_text("{ broken", encoding="utf-8")

    governed = JsonlVocabularyRepository(str(tmp_path)).load(_KIND)[0]

    # Corrupt sidecar -> usage falls back to "never used" without crashing.
    assert governed.entry.id == "a"
    assert governed.usage.hits == 0


def test_hand_added_source_without_usage_is_never_used(tmp_path) -> None:
    source = tmp_path / "fuzzy_word.jsonl"
    source.write_text(
        json.dumps({"id": "hand", "term": "Springfield", "aliases": [], "origin": "default"})
        + "\n",
        encoding="utf-8",
    )

    governed = JsonlVocabularyRepository(str(tmp_path)).load(_KIND)[0]

    assert governed.usage.hits == 0
    assert governed.usage.last_used == datetime.fromtimestamp(0)


def test_unknown_origin_defaults_to_default(tmp_path) -> None:
    source = tmp_path / "fuzzy_word.jsonl"
    source.write_text(
        json.dumps({"id": "x", "term": "y", "aliases": [], "origin": "bogus"}) + "\n",
        encoding="utf-8",
    )

    governed = JsonlVocabularyRepository(str(tmp_path)).load(_KIND)[0]

    assert governed.entry.origin is VocabularyOrigin.DEFAULT


def test_kinds_use_separate_files(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(VocabularyEntry(id="f", kind=VocabularyKind.FUZZY_WORD, term="fz"), _NOW)
    repo.add(VocabularyEntry(id="m", kind=VocabularyKind.WORD_MAPPING, term="mp"), _NOW)

    assert [g.id for g in repo.load(VocabularyKind.FUZZY_WORD)] == ["f"]
    assert [g.id for g in repo.load(VocabularyKind.WORD_MAPPING)] == ["m"]
    assert (tmp_path / "fuzzy_word.jsonl").is_file()
    assert (tmp_path / "word_mapping.jsonl").is_file()


def test_mark_used_spans_kinds(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(
        VocabularyEntry(id="f", kind=VocabularyKind.FUZZY_WORD, term="fz"), datetime(2026, 1, 1)
    )
    repo.add(
        VocabularyEntry(id="m", kind=VocabularyKind.WORD_MAPPING, term="mp"), datetime(2026, 1, 1)
    )

    repo.mark_used(["f", "m"], _NOW)

    assert repo.load(VocabularyKind.FUZZY_WORD)[0].usage.hits == 1
    assert repo.load(VocabularyKind.WORD_MAPPING)[0].usage.hits == 1
