"""Tests for the AddWordMapping use case (ADR-0004 unification).

The UI "Add word mapping" action writes into the repository source of truth through this
use case. These cover adding a fresh mapping, merging aliases into an existing replacement,
the no-op on blank input, and the slug-id collision suffix.
"""

from __future__ import annotations

from datetime import datetime

from vaivox.application.add_vocabulary import AddWordMapping
from vaivox.domain.vocabulary.model import VocabularyEntry, VocabularyKind
from vaivox.infrastructure.vocabulary.jsonl_repository import JsonlVocabularyRepository

_NOW = datetime(2026, 6, 18, 12, 0, 0)


class _Clock:
    def now(self) -> datetime:
        return _NOW


def _mappings(repo: JsonlVocabularyRepository) -> dict[str, tuple[str, ...]]:
    return {g.entry.term: g.entry.aliases for g in repo.load(VocabularyKind.WORD_MAPPING)}


def test_add_creates_a_new_mapping_entry(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    AddWordMapping(repo, _Clock()).execute("kb;kobby", "Kobuleti")

    entries = repo.load(VocabularyKind.WORD_MAPPING)
    assert len(entries) == 1
    assert entries[0].entry.term == "Kobuleti"
    assert entries[0].entry.aliases == ("kb", "kobby")  # sorted + de-duplicated
    assert entries[0].id == "kobuleti"


def test_add_merges_aliases_into_an_existing_replacement(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(
        VocabularyEntry(
            id="kobuleti", kind=VocabularyKind.WORD_MAPPING, term="Kobuleti", aliases=("kb",)
        ),
        _NOW,
    )

    AddWordMapping(repo, _Clock()).execute("kobby;kb", "Kobuleti")

    entries = repo.load(VocabularyKind.WORD_MAPPING)
    assert len(entries) == 1  # merged, not duplicated
    assert entries[0].entry.aliases == ("kb", "kobby")


def test_blank_input_is_a_no_op(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    add = AddWordMapping(repo, _Clock())

    add.execute("", "Kobuleti")
    add.execute("kb", "   ")
    add.execute("  ;  ", "Kobuleti")

    assert repo.load(VocabularyKind.WORD_MAPPING) == []


def test_distinct_replacements_with_colliding_slugs_get_suffixed_ids(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    add = AddWordMapping(repo, _Clock())

    add.execute("a", "Kobuleti")
    add.execute("b", "kobuleti!")  # slugifies to the same base

    ids = sorted(g.id for g in repo.load(VocabularyKind.WORD_MAPPING))
    assert ids == ["kobuleti", "kobuleti-2"]
