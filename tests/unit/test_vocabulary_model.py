"""Unit tests for the structured vocabulary value objects (ADR-0004)."""

from __future__ import annotations

from datetime import datetime

from vaivox.domain.vocabulary.model import (
    EvictionPolicy,
    EvictionResult,
    GovernedEntry,
    UsageStats,
    VocabularyEntry,
    VocabularyKind,
    VocabularyOrigin,
    credited_ids,
)


def _entry(entry_id: str, origin: VocabularyOrigin = VocabularyOrigin.DEFAULT) -> VocabularyEntry:
    return VocabularyEntry(
        id=entry_id,
        kind=VocabularyKind.FUZZY_WORD,
        term="bogey dope",
        origin=origin,
    )


def test_default_entry_is_not_evictable() -> None:
    assert _entry("e1", VocabularyOrigin.DEFAULT).is_evictable is False


def test_learned_entry_is_evictable() -> None:
    assert _entry("e1", VocabularyOrigin.LEARNED).is_evictable is True


def test_entry_defaults() -> None:
    entry = VocabularyEntry(id="e1", kind=VocabularyKind.WORD_MAPPING, term="Texaco")
    assert entry.aliases == ()
    assert entry.origin is VocabularyOrigin.DEFAULT


def test_usage_stamped_increments_hits_and_refreshes_recency() -> None:
    seed = UsageStats(last_used=datetime(2026, 1, 1), hits=2)
    when = datetime(2026, 6, 18, 12, 0, 0)

    stamped = seed.stamped(when)

    assert stamped.hits == 3
    assert stamped.last_used == when
    # Originals are immutable value objects — unchanged.
    assert seed.hits == 2
    assert seed.last_used == datetime(2026, 1, 1)


def test_governed_entry_delegates_id_and_evictability() -> None:
    entry = _entry("e7", VocabularyOrigin.LEARNED)
    governed = GovernedEntry(entry=entry, usage=UsageStats(last_used=datetime(2026, 1, 1)))

    assert governed.id == "e7"
    assert governed.is_evictable is True


def test_eviction_policy_rejects_negative_cap() -> None:
    try:
        EvictionPolicy(max_entries=-1)
    except ValueError:
        return
    raise AssertionError("expected ValueError for negative max_entries")


def test_eviction_result_evicted_ids() -> None:
    evicted = (
        GovernedEntry(_entry("a"), UsageStats(last_used=datetime(2026, 1, 1))),
        GovernedEntry(_entry("b"), UsageStats(last_used=datetime(2026, 1, 1))),
    )
    result = EvictionResult(kept=(), evicted=evicted)

    assert result.evicted_ids == ("a", "b")


def test_credited_ids_dedupes_preserving_order() -> None:
    stats = UsageStats(last_used=datetime(2026, 1, 1))
    entries = [
        GovernedEntry(_entry("b"), stats),
        GovernedEntry(_entry("a"), stats),
        GovernedEntry(_entry("b"), stats),
    ]

    assert credited_ids(entries) == ("b", "a")
