"""Tests for the repository-backed vocabulary provider (ADR-0004 unification).

The provider projects the structured JSONL repository down to the flat ``word_mappings`` /
``fuzzy_words`` the reconciliation pipeline reads, and is the seam that makes the engine and
the introspection ``GET /vocabulary`` share one source of truth. These exercise the
projection (inverse of the migration), the live read (a UI add is visible), and the
sub-second TTL cache.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from vaivox.application.ports import VocabularyProvider
from vaivox.domain.vocabulary.model import VocabularyEntry, VocabularyKind, VocabularyOrigin
from vaivox.infrastructure.vocabulary.jsonl_repository import JsonlVocabularyRepository
from vaivox.infrastructure.vocabulary.repository_provider import RepositoryVocabularyProvider


class _StubClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


_START = datetime(2026, 6, 18, 12, 0, 0)


def test_provider_conforms_to_port(tmp_path) -> None:
    provider: VocabularyProvider = RepositoryVocabularyProvider(
        JsonlVocabularyRepository(str(tmp_path)), _StubClock(_START)
    )
    assert isinstance(provider, VocabularyProvider)


def test_word_mappings_are_flattened_to_alias_to_term(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(
        VocabularyEntry(
            id="kobuleti",
            kind=VocabularyKind.WORD_MAPPING,
            term="Kobuleti",
            aliases=("kb", "kobby"),
        ),
        _START,
    )
    provider = RepositoryVocabularyProvider(repo, _StubClock(_START))

    assert provider.get_word_mappings() == {"kb": "Kobuleti", "kobby": "Kobuleti"}


def test_fuzzy_words_are_the_entry_terms_in_order(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(VocabularyEntry(id="senaki", kind=VocabularyKind.FUZZY_WORD, term="Senaki"), _START)
    repo.add(VocabularyEntry(id="texaco", kind=VocabularyKind.FUZZY_WORD, term="Texaco"), _START)
    provider = RepositoryVocabularyProvider(repo, _StubClock(_START))

    assert list(provider.get_fuzzy_words()) == ["Senaki", "Texaco"]


def test_read_is_live_after_the_cache_window_elapses(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = _StubClock(_START)
    provider = RepositoryVocabularyProvider(repo, clock)

    assert provider.get_fuzzy_words() == []  # primes the cache

    repo.add(VocabularyEntry(id="senaki", kind=VocabularyKind.FUZZY_WORD, term="Senaki"), _START)
    clock.advance(2.0)  # past the sub-second TTL

    assert list(provider.get_fuzzy_words()) == ["Senaki"]


def test_within_the_cache_window_the_repository_is_not_re_read(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = _StubClock(_START)
    provider = RepositoryVocabularyProvider(repo, clock)

    assert provider.get_fuzzy_words() == []  # primes the cache at t0

    repo.add(VocabularyEntry(id="senaki", kind=VocabularyKind.FUZZY_WORD, term="Senaki"), _START)
    # No time advance: still within the TTL, so the stale (empty) projection is served.
    assert provider.get_fuzzy_words() == []


def test_learned_and_default_entries_both_project(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    repo.add(
        VocabularyEntry(
            id="a",
            kind=VocabularyKind.FUZZY_WORD,
            term="Alpha",
            origin=VocabularyOrigin.DEFAULT,
        ),
        _START,
    )
    repo.add(
        VocabularyEntry(
            id="b",
            kind=VocabularyKind.FUZZY_WORD,
            term="Bravo",
            origin=VocabularyOrigin.LEARNED,
        ),
        _START,
    )
    provider = RepositoryVocabularyProvider(repo, _StubClock(_START))

    assert set(provider.get_fuzzy_words()) == {"Alpha", "Bravo"}
