"""Unit tests for the LearnFromOutcome use case (ADR-0006).

Drives the use case with a fake repository, a fake clock, and synthetic snap/match values to
pin: the three match states (matched / not-matched / unknown), the abstain-on-its-own path,
propose-only vs auto-apply, the candidate fallback (snapped vs abstained), and the
never-fatal guarantee.
"""

from __future__ import annotations

from datetime import datetime

from vaivox.application.learn_from_outcome import ApplyPolicy, LearnFromOutcome
from vaivox.domain.reconciliation.model import ReconciliationResult
from vaivox.domain.reconciliation.snapper import NearMiss, SnapDecision, SnapResult
from vaivox.domain.telemetry.model import MatchOutcome
from vaivox.domain.vocabulary.model import GovernedEntry, VocabularyEntry, VocabularyKind

_NOW = datetime(2026, 6, 22, 12, 0, 0)


class FakeClock:
    def now(self) -> datetime:
        return _NOW


class FakeRepository:
    def __init__(self, *, fail_on_add: bool = False) -> None:
        self.added: list[tuple[VocabularyEntry, datetime]] = []
        self._fail_on_add = fail_on_add

    def load(self, kind: VocabularyKind) -> list[GovernedEntry]:
        return []

    def mark_used(self, ids, when) -> None:  # pragma: no cover - unused here
        raise NotImplementedError

    def add(self, entry: VocabularyEntry, when: datetime) -> None:
        if self._fail_on_add:
            raise OSError("disk full")
        self.added.append((entry, when))

    def replace_entries(self, kind, kept) -> None:  # pragma: no cover - unused here
        raise NotImplementedError


def _result(command_text: str) -> ReconciliationResult:
    return ReconciliationResult(
        raw_text=command_text, cleaned_text=command_text, command_text=command_text
    )


def _abstained(*near_misses: tuple[str, float]) -> SnapResult:
    return SnapResult(
        decision=SnapDecision.ABSTAINED,
        text="texaco rejon",
        candidate=near_misses[0][0] if near_misses else None,
        score=near_misses[0][1] if near_misses else 0.0,
        near_misses=tuple(NearMiss(phrase=p, score=s) for p, s in near_misses),
    )


def _snapped(phrase: str, score: float) -> SnapResult:
    return SnapResult(decision=SnapDecision.SNAPPED, text=phrase, candidate=phrase, score=score)


def _learner(repo: FakeRepository, policy: ApplyPolicy) -> LearnFromOutcome:
    return LearnFromOutcome(repo, FakeClock(), policy=policy)


# -- the three match states ----------------------------------------------------------


def test_matched_true_never_learns() -> None:
    repo = FakeRepository()
    snap = _abstained(("Texaco request rejoin", 75.0))

    proposal = _learner(repo, ApplyPolicy.AUTO_APPLY).execute(
        _result("texaco rejon"), snap, MatchOutcome(matched=True)
    )

    assert proposal is None
    assert repo.added == []  # a confirmed match is nothing to learn from


def test_matched_false_learns_from_near_miss() -> None:
    repo = FakeRepository()
    snap = _abstained(("Texaco request rejoin", 75.0))

    proposal = _learner(repo, ApplyPolicy.AUTO_APPLY).execute(
        _result("texaco rejon"), snap, MatchOutcome(matched=False)
    )

    assert proposal is not None
    assert proposal.nearest_phrase == "Texaco request rejoin"
    assert len(repo.added) == 1  # auto-apply wrote a LEARNED entry


def test_unknown_outcome_without_abstain_does_not_learn() -> None:
    # match=None (unknown) and a snap that did NOT abstain (raw) -> no signal, no learning.
    repo = FakeRepository()
    snap = SnapResult(decision=SnapDecision.RAW, text="texaco rejon", candidate="x", score=10.0)

    proposal = _learner(repo, ApplyPolicy.AUTO_APPLY).execute(_result("texaco rejon"), snap, None)

    assert proposal is None
    assert repo.added == []


# -- abstain on its own (no match signal yet) ----------------------------------------


def test_abstain_alone_is_a_near_miss_even_when_match_is_unknown() -> None:
    # A snap abstain is a learnable near-miss in its own right (the snapper found close
    # candidates), even when the match outcome is unknown (None).
    repo = FakeRepository()
    snap = _abstained(("Texaco request rejoin", 72.0))

    proposal = _learner(repo, ApplyPolicy.AUTO_APPLY).execute(_result("texaco rejon"), snap, None)

    assert proposal is not None
    assert len(repo.added) == 1


# -- candidate fallback (snapped but not matched) ------------------------------------


def test_snapped_but_not_matched_learns_from_the_snapped_candidate() -> None:
    # The snapper snapped (no near_misses list), but VoiceAttack still reported not-matched.
    # The single best candidate is used as the phrase to learn toward.
    repo = FakeRepository()
    snap = _snapped("Texaco request rejoin", 97.0)

    proposal = _learner(repo, ApplyPolicy.AUTO_APPLY).execute(
        _result("texaco request rejon"), snap, MatchOutcome(matched=False)
    )

    assert proposal is not None
    assert proposal.nearest_phrase == "Texaco request rejoin"
    assert len(repo.added) == 1


# -- policy --------------------------------------------------------------------------


def test_propose_only_returns_proposal_but_writes_nothing() -> None:
    repo = FakeRepository()
    snap = _abstained(("Texaco request rejoin", 75.0))

    proposal = _learner(repo, ApplyPolicy.PROPOSE_ONLY).execute(
        _result("texaco rejon"), snap, MatchOutcome(matched=False)
    )

    assert proposal is not None  # observable for human review
    assert repo.added == []  # but nothing is written (human-in-the-loop default)


# -- no candidates / kneeboard -------------------------------------------------------


def test_no_snap_candidates_proposes_nothing() -> None:
    # An empty phrase index -> a snap with no candidate -> nothing to learn toward.
    repo = FakeRepository()
    snap = SnapResult(decision=SnapDecision.RAW, text="texaco rejon", candidate=None)

    proposal = _learner(repo, ApplyPolicy.AUTO_APPLY).execute(
        _result("texaco rejon"), snap, MatchOutcome(matched=False)
    )

    assert proposal is None
    assert repo.added == []


def test_kneeboard_path_snap_none_proposes_nothing() -> None:
    repo = FakeRepository()

    proposal = _learner(repo, ApplyPolicy.AUTO_APPLY).execute(
        _result("note something"), None, MatchOutcome(matched=False)
    )

    assert proposal is None
    assert repo.added == []


# -- never fatal ---------------------------------------------------------------------


def test_repository_failure_is_swallowed() -> None:
    repo = FakeRepository(fail_on_add=True)
    snap = _abstained(("Texaco request rejoin", 75.0))

    # Must not raise — learning is best-effort and never breaks dispatch.
    proposal = _learner(repo, ApplyPolicy.AUTO_APPLY).execute(
        _result("texaco rejon"), snap, MatchOutcome(matched=False)
    )

    assert proposal is None  # the failed apply degrades to "no proposal", logged
