"""Unit tests for the pure near-miss proposal function (ADR-0006, domain).

:func:`~vaivox.domain.vocabulary.learning.propose_from_near_miss` is a pure domain function:
no I/O, no clock, no repository. These tests pin its deterministic shaping of a learned
``WORD_MAPPING`` proposal from a near-miss, and its "nothing to learn" guards.
"""

from __future__ import annotations

from vaivox.domain.vocabulary.learning import propose_from_near_miss
from vaivox.domain.vocabulary.model import VocabularyKind, VocabularyOrigin


def test_proposes_learned_word_mapping_from_best_candidate() -> None:
    proposal = propose_from_near_miss(
        "texaco request rejon",
        [("Texaco request rejoin", 92.0), ("Texaco request fuel", 55.0)],
    )

    assert proposal is not None
    assert proposal.utterance == "texaco request rejon"
    assert proposal.nearest_phrase == "Texaco request rejoin"
    assert proposal.score == 92.0
    entry = proposal.entry
    assert entry.kind is VocabularyKind.WORD_MAPPING
    assert entry.origin is VocabularyOrigin.LEARNED  # only learned entries are evictable
    assert entry.term == "Texaco request rejoin"  # the canonical replacement
    assert entry.aliases == ("texaco request rejon",)  # the spoken near-miss


def test_blank_utterance_proposes_nothing() -> None:
    assert propose_from_near_miss("   ", [("Texaco request rejoin", 90.0)]) is None


def test_no_candidates_proposes_nothing() -> None:
    assert propose_from_near_miss("texaco rejon", []) is None


def test_utterance_equal_to_best_candidate_proposes_nothing() -> None:
    # Already the valid phrase (case/space-insensitive) -> nothing to correct toward.
    proposal = propose_from_near_miss("texaco  request  rejoin", [("Texaco request rejoin", 100.0)])
    assert proposal is None


def test_generated_id_avoids_collision_with_existing_ids() -> None:
    first = propose_from_near_miss("texaco rejon", [("Texaco request rejoin", 90.0)])
    assert first is not None
    base_id = first.entry.id

    second = propose_from_near_miss(
        "texaco rejjon",
        [("Texaco request rejoin", 90.0)],
        existing_ids=frozenset({base_id}),
    )
    assert second is not None
    assert second.entry.id != base_id  # a -N suffix avoids the collision


def test_is_pure_default_existing_ids_not_shared_across_calls() -> None:
    # The default frozenset() must not accumulate state between calls (mutable-default trap).
    a = propose_from_near_miss("texaco rejon", [("Texaco request rejoin", 90.0)])
    b = propose_from_near_miss("texaco rejon", [("Texaco request rejoin", 90.0)])
    assert a is not None and b is not None
    assert a.entry.id == b.entry.id  # identical inputs -> identical id (no leaked state)
