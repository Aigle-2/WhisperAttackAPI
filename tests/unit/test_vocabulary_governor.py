"""Unit tests for the VocabularyGovernor domain service (ADR-0004)."""

from __future__ import annotations

from datetime import datetime, timedelta

from vaivox.domain.vocabulary.governor import VocabularyGovernor
from vaivox.domain.vocabulary.model import (
    EvictionPolicy,
    GovernedEntry,
    UsageStats,
    VocabularyEntry,
    VocabularyKind,
    VocabularyOrigin,
)

_NOW = datetime(2026, 6, 18, 12, 0, 0)


def _governed(
    entry_id: str,
    *,
    last_used: datetime,
    hits: int = 0,
    origin: VocabularyOrigin = VocabularyOrigin.LEARNED,
) -> GovernedEntry:
    return GovernedEntry(
        entry=VocabularyEntry(
            id=entry_id,
            kind=VocabularyKind.FUZZY_WORD,
            term=entry_id,
            origin=origin,
        ),
        usage=UsageStats(last_used=last_used, hits=hits),
    )


# -- ranking -------------------------------------------------------------------------


def test_rank_orders_by_recency_then_hits_then_id() -> None:
    governor = VocabularyGovernor()
    older = _governed("old", last_used=_NOW - timedelta(days=2), hits=99)
    newer = _governed("new", last_used=_NOW, hits=1)
    # Same recency + hits as `newer`; ascending-id tie-break puts "aaa" before "new".
    tie = _governed("aaa", last_used=_NOW, hits=1)

    ranked = governor.rank([older, newer, tie])

    assert [g.id for g in ranked] == ["aaa", "new", "old"]


def test_rank_tie_break_is_ascending_id_under_descending_sort() -> None:
    governor = VocabularyGovernor()
    same = {"last_used": _NOW, "hits": 5}
    a = _governed("a", **same)
    b = _governed("b", **same)
    c = _governed("c", **same)

    ranked = governor.rank([c, a, b])

    assert [g.id for g in ranked] == ["a", "b", "c"]


# -- eviction ------------------------------------------------------------------------


def test_no_cap_evicts_nothing() -> None:
    governor = VocabularyGovernor()
    entries = [_governed(f"e{i}", last_used=_NOW - timedelta(days=i)) for i in range(5)]

    result = governor.govern(entries, EvictionPolicy(max_entries=None), _NOW)

    assert result.evicted == ()
    assert len(result.kept) == 5


def test_under_cap_evicts_nothing() -> None:
    governor = VocabularyGovernor()
    entries = [_governed("a", last_used=_NOW), _governed("b", last_used=_NOW)]

    result = governor.govern(entries, EvictionPolicy(max_entries=5), _NOW)

    assert result.evicted == ()


def test_evicts_least_recently_used_over_cap() -> None:
    governor = VocabularyGovernor()
    fresh = _governed("fresh", last_used=_NOW)
    mid = _governed("mid", last_used=_NOW - timedelta(days=1))
    stale = _governed("stale", last_used=_NOW - timedelta(days=10))

    result = governor.govern([fresh, mid, stale], EvictionPolicy(max_entries=2), _NOW)

    assert result.evicted_ids == ("stale",)
    assert [g.id for g in result.kept] == ["fresh", "mid"]


def test_default_entries_are_protected_even_when_stale() -> None:
    governor = VocabularyGovernor()
    protected = _governed(
        "curated", last_used=_NOW - timedelta(days=100), origin=VocabularyOrigin.DEFAULT
    )
    learned_fresh = _governed("learned", last_used=_NOW)

    # Cap of 1, but the stale entry is DEFAULT and cannot be evicted, so the learned
    # (fresher) entry is dropped instead and the kept set may exceed the soft cap.
    result = governor.govern([protected, learned_fresh], EvictionPolicy(max_entries=1), _NOW)

    assert result.evicted_ids == ("learned",)
    assert [g.id for g in result.kept] == ["curated"]


def test_all_protected_keeps_everyone_over_cap() -> None:
    governor = VocabularyGovernor()
    entries = [
        _governed("a", last_used=_NOW, origin=VocabularyOrigin.DEFAULT),
        _governed("b", last_used=_NOW - timedelta(days=1), origin=VocabularyOrigin.DEFAULT),
    ]

    result = governor.govern(entries, EvictionPolicy(max_entries=1), _NOW)

    assert result.evicted == ()
    assert len(result.kept) == 2


def test_grace_window_shields_brand_new_entries() -> None:
    governor = VocabularyGovernor()
    stale = _governed("stale", last_used=_NOW - timedelta(days=30))
    # Just-added: last_used == now, well inside a 1-day grace window.
    brand_new = _governed("new", last_used=_NOW - timedelta(minutes=1))

    policy = EvictionPolicy(max_entries=1, grace_window=timedelta(days=1))
    result = governor.govern([stale, brand_new], policy, _NOW)

    # The new entry is shielded; the stale one is evicted instead.
    assert result.evicted_ids == ("stale",)
    assert [g.id for g in result.kept] == ["new"]


def test_grace_window_does_not_shield_aged_out_entries() -> None:
    governor = VocabularyGovernor()
    stale = _governed("stale", last_used=_NOW - timedelta(days=30))
    aged = _governed("aged", last_used=_NOW - timedelta(days=2))

    # Both are older than the 1-day grace window; the least-recently-used goes.
    policy = EvictionPolicy(max_entries=1, grace_window=timedelta(days=1))
    result = governor.govern([stale, aged], policy, _NOW)

    assert result.evicted_ids == ("stale",)


def test_grace_can_force_keeping_above_cap() -> None:
    governor = VocabularyGovernor()
    in_grace_1 = _governed("g1", last_used=_NOW)
    in_grace_2 = _governed("g2", last_used=_NOW - timedelta(minutes=5))

    # Cap of 1 but both are inside grace, so nothing is evictable this pass.
    policy = EvictionPolicy(max_entries=1, grace_window=timedelta(days=1))
    result = governor.govern([in_grace_1, in_grace_2], policy, _NOW)

    assert result.evicted == ()
    assert len(result.kept) == 2


# -- Tier 1 attribution --------------------------------------------------------------


def test_tier1_credits_edit_whose_output_survives() -> None:
    governor = VocabularyGovernor()
    matched = ["request", "bogey", "dope"]
    edits = {
        "edit_bogey": ["bogey"],  # survives -> credited
        "edit_dropped": ["wilco"],  # does not survive -> not credited
    }

    assert governor.attribute_tier1(matched, edits) == ("edit_bogey",)


def test_tier1_is_case_and_whitespace_insensitive() -> None:
    governor = VocabularyGovernor()
    matched = ["  Bogey ", "Dope"]
    edits = {"e1": ["bogey"], "e2": ["DOPE"]}

    assert governor.attribute_tier1(matched, edits) == ("e1", "e2")


def test_tier1_credits_edit_if_any_output_token_survives() -> None:
    governor = VocabularyGovernor()
    matched = ["nine", "line"]
    edits = {"multi": ["niner", "nine"]}  # one of two output tokens survives

    assert governor.attribute_tier1(matched, edits) == ("multi",)


def test_tier1_no_survivors_credits_nothing() -> None:
    governor = VocabularyGovernor()
    assert governor.attribute_tier1(["alpha"], {"e1": ["bravo"]}) == ()


def test_tier1_ignores_blank_output_tokens() -> None:
    governor = VocabularyGovernor()
    # A blank matched token must not let a blank-output edit get spurious credit.
    assert governor.attribute_tier1(["", "alpha"], {"e1": ["   "]}) == ()
