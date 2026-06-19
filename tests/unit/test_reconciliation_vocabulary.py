"""Tests for the structured-vocabulary projection used by reconciliation."""

from __future__ import annotations

from datetime import datetime

from vaivox.application.vocabulary_commands import AddWordMapping
from vaivox.domain.vocabulary.model import VocabularyEntry, VocabularyKind
from vaivox.infrastructure.vocabulary.jsonl_repository import JsonlVocabularyRepository
from vaivox.infrastructure.vocabulary.reconciliation_vocabulary import (
    RepositoryReconciliationVocabulary,
)


class FakeClock:
    def now(self):
        return datetime(2026, 6, 19, 12, 0, 0)


def test_projection_reads_structured_fuzzy_words_and_mappings(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(
        VocabularyEntry(id="kobuleti", kind=VocabularyKind.FUZZY_WORD, term="Kobuleti"),
        FakeClock().now(),
    )
    repo.add(
        VocabularyEntry(
            id="tower",
            kind=VocabularyKind.WORD_MAPPING,
            term="Tower",
            aliases=("tawa", "tower"),
        ),
        FakeClock().now(),
    )
    vocabulary = RepositoryReconciliationVocabulary(repo)

    assert vocabulary.get_fuzzy_words() == ["Kobuleti"]
    assert vocabulary.get_word_mappings() == {"tawa": "Tower", "tower": "Tower"}


def test_add_word_mapping_extends_existing_default_entry(tmp_path) -> None:
    defaults = tmp_path / "defaults"
    data = tmp_path / "data"
    defaults.mkdir()
    data.mkdir()
    (defaults / "word_mapping.jsonl").write_text(
        '{"id": "tower", "term": "Tower", "aliases": ["tawa"], "origin": "default"}\n',
        encoding="utf-8",
    )
    repo = JsonlVocabularyRepository(str(data), default_source_dir=str(defaults))

    entry = AddWordMapping(repo, FakeClock()).execute("towah", "Tower")

    assert entry is not None
    assert entry.aliases == ("tawa", "towah")
    vocabulary = RepositoryReconciliationVocabulary(repo)
    assert vocabulary.get_word_mappings() == {"tawa": "Tower", "towah": "Tower"}
    assert (data / "word_mapping.jsonl").is_file()
