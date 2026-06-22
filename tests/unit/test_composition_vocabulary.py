"""Tests for the vocabulary auto-seed in the composition root (ADR-0004 unification).

On first launch the structured JSONL repository is seeded from the legacy flat
``word_mappings.txt`` / ``fuzzy_words.txt`` so the engine (which now reads the repository)
sees the same vocabulary the flat-file loader used to provide. These verify the seed runs
when the source is absent, is skipped (never overwrites) on a later launch, and that the
projected provider reproduces the flat-file vocabulary — the behavioural-parity guarantee.
"""

from __future__ import annotations

from vaivox.composition import build_vocabulary_repository
from vaivox.domain.vocabulary.model import VocabularyKind
from vaivox.infrastructure.config.settings import VaivoxConfiguration
from vaivox.infrastructure.system_clock import SystemClock
from vaivox.infrastructure.vocabulary.repository_provider import RepositoryVocabularyProvider


def _config(tmp_path, *, word_mappings: str, fuzzy_words: str) -> VaivoxConfiguration:
    app_dir = tmp_path / "app"
    data_dir = tmp_path / "data"
    app_dir.mkdir()
    data_dir.mkdir()
    (app_dir / "settings.cfg").write_text("stt_backend=elevenlabs\n", encoding="utf-8")
    (app_dir / "word_mappings.txt").write_text(word_mappings, encoding="utf-8")
    (app_dir / "fuzzy_words.txt").write_text(fuzzy_words, encoding="utf-8")
    return VaivoxConfiguration(str(app_dir), str(data_dir))


def test_first_launch_seeds_the_repository_from_the_flat_files(tmp_path) -> None:
    config = _config(tmp_path, word_mappings="kb=Kobuleti\n", fuzzy_words="Senaki\nTexaco\n")

    repo = build_vocabulary_repository(config, SystemClock())

    fuzzy = {g.entry.term for g in repo.load(VocabularyKind.FUZZY_WORD)}
    mappings = repo.load(VocabularyKind.WORD_MAPPING)
    assert fuzzy == {"Senaki", "Texaco"}
    assert mappings[0].entry.term == "Kobuleti"
    assert mappings[0].entry.aliases == ("kb",)


def test_seed_is_skipped_when_a_source_already_exists(tmp_path) -> None:
    # A pre-existing JSONL source must not be overwritten with the flat-file seed.
    data_dir = tmp_path / "data"
    config = _config(tmp_path, word_mappings="kb=Kobuleti\n", fuzzy_words="Senaki\n")
    (data_dir / f"{VocabularyKind.FUZZY_WORD.value}.jsonl").write_text(
        '{"id": "krymsk", "term": "Krymsk", "aliases": [], "origin": "learned"}\n',
        encoding="utf-8",
    )

    repo = build_vocabulary_repository(config, SystemClock())

    fuzzy = {g.entry.term for g in repo.load(VocabularyKind.FUZZY_WORD)}
    assert fuzzy == {"Krymsk"}  # the flat-file "Senaki" seed did not run


def test_projected_vocabulary_matches_the_flat_files(tmp_path) -> None:
    # The whole point: after the seed, the provider reproduces the flat-file vocabulary.
    config = _config(
        tmp_path,
        word_mappings="inter=Enter\nwilco roger=wilco\n",
        fuzzy_words="Kobuleti\nSenaki\n",
    )

    repo = build_vocabulary_repository(config, SystemClock())
    provider = RepositoryVocabularyProvider(repo, SystemClock())

    assert dict(provider.get_word_mappings()) == dict(config.get_word_mappings())
    assert set(provider.get_fuzzy_words()) == set(config.get_fuzzy_words())
