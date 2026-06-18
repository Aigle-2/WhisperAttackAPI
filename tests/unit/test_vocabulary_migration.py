"""Unit tests for the legacy -> JSONL vocabulary migration (ADR-0004).

Covers the pure conversion (grouping aliases by replacement, slug ids, collision suffixes,
blank skipping) and the end-to-end seed through a real JSONL repository on a temp dir,
including idempotency on a re-run.
"""

from __future__ import annotations

from datetime import datetime

from vaivox.domain.vocabulary.model import VocabularyKind, VocabularyOrigin
from vaivox.infrastructure.vocabulary.jsonl_repository import JsonlVocabularyRepository
from vaivox.infrastructure.vocabulary.migration import (
    legacy_to_entries,
    migrate_legacy_vocabulary,
)

WHEN = datetime(2026, 6, 18, 12, 0, 0)


def test_fuzzy_words_become_fuzzy_entries_with_slug_ids():
    entries = legacy_to_entries({}, ["Kobuleti", "Senaki"])

    assert [(e.kind, e.id, e.term, e.aliases, e.origin) for e in entries] == [
        (VocabularyKind.FUZZY_WORD, "kobuleti", "Kobuleti", (), VocabularyOrigin.DEFAULT),
        (VocabularyKind.FUZZY_WORD, "senaki", "Senaki", (), VocabularyOrigin.DEFAULT),
    ]


def test_word_mappings_group_aliases_by_replacement():
    # Two aliases share the "Kobuleti" replacement; they collapse into one entry.
    entries = legacy_to_entries({"kb": "Kobuleti", "kobby": "Kobuleti", "snk": "Senaki"}, [])

    mappings = [e for e in entries if e.kind is VocabularyKind.WORD_MAPPING]
    assert (mappings[0].id, mappings[0].term, mappings[0].aliases) == (
        "kobuleti",
        "Kobuleti",
        ("kb", "kobby"),  # grouped and sorted
    )
    assert (mappings[1].term, mappings[1].aliases) == ("Senaki", ("snk",))


def test_colliding_slugs_are_disambiguated_within_a_kind():
    entries = legacy_to_entries({}, ["Kobuleti", "kobuleti!", "  KOBULETI  "])

    assert [e.id for e in entries] == ["kobuleti", "kobuleti-2", "kobuleti-3"]


def test_blank_terms_and_aliases_are_skipped():
    entries = legacy_to_entries({"  ": "Senaki", "x": "   "}, ["", "   ", "Texaco"])

    assert [e.term for e in entries] == ["Texaco"]  # both blank mappings + blank words dropped


def test_migration_seeds_the_repository_and_is_idempotent(tmp_path):
    repository = JsonlVocabularyRepository(str(tmp_path))

    report = migrate_legacy_vocabulary({"kb": "Kobuleti"}, ["Senaki", "Texaco"], repository, WHEN)

    assert (report.fuzzy_words, report.word_mappings, report.total) == (2, 1, 3)
    fuzzy = {governed.entry.term for governed in repository.load(VocabularyKind.FUZZY_WORD)}
    mappings = repository.load(VocabularyKind.WORD_MAPPING)
    assert fuzzy == {"Senaki", "Texaco"}
    assert mappings[0].entry.term == "Kobuleti"
    assert mappings[0].entry.aliases == ("kb",)

    # Re-running must not duplicate (the repository skips ids already present).
    migrate_legacy_vocabulary({"kb": "Kobuleti"}, ["Senaki", "Texaco"], repository, WHEN)
    assert len(repository.load(VocabularyKind.FUZZY_WORD)) == 2
    assert len(repository.load(VocabularyKind.WORD_MAPPING)) == 1
