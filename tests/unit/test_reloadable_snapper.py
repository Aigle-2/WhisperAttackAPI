"""Unit tests for the idle-gated swap primitive and the reloadable phrase snapper.

Covers the ADR-0009 contract: a staged value swaps in only at an idle checkpoint (now if
idle, else deferred to the next read), the latest staged value wins, an already-captured
reference is unaffected by a later swap, and the observer fires once per applied swap. The
``ReloadablePhraseSnapper`` layer adds: it satisfies the ``PhraseMatcher`` port, delegates
``snap`` to the live index, and reports the new phrase count when an index swaps in.
"""

from __future__ import annotations

from vaivox.application.ports import PhraseMatcher
from vaivox.domain.reconciliation.snapper import PhraseSnapper, SnapDecision
from vaivox.infrastructure.reload.idle_gated import IdleGatedSwap
from vaivox.infrastructure.reload.phrase_snapper import ReloadablePhraseSnapper

INDEX = ["Texaco request rejoin", "Overlord bogey dope"]
OTHER_INDEX = ["Colt request startup", "Springfield request startup"]


# --- IdleGatedSwap -----------------------------------------------------------------


def test_swap_applies_immediately_when_idle() -> None:
    swap: IdleGatedSwap[str] = IdleGatedSwap("a", is_idle=lambda: True)

    applied = swap.request_swap("b")

    assert applied is True
    assert swap.current() == "b"


def test_swap_defers_while_busy_then_applies_at_next_read_when_idle() -> None:
    idle = {"v": False}
    swap: IdleGatedSwap[str] = IdleGatedSwap("a", is_idle=lambda: idle["v"])

    applied = swap.request_swap("b")

    assert applied is False  # staged, not applied
    assert swap.current() == "a"  # still the old value while busy

    idle["v"] = True
    assert swap.current() == "b"  # the deferred swap lands at the next idle read


def test_latest_staged_value_wins_while_busy() -> None:
    idle = {"v": False}
    swap: IdleGatedSwap[str] = IdleGatedSwap("a", is_idle=lambda: idle["v"])

    swap.request_swap("b")
    swap.request_swap("c")  # supersedes the still-pending "b"

    idle["v"] = True
    assert swap.current() == "c"


def test_captured_reference_is_unaffected_by_a_later_swap() -> None:
    swap: IdleGatedSwap[list[int]] = IdleGatedSwap([1], is_idle=lambda: True)

    captured = swap.current()  # an in-flight consumer holds this reference
    swap.request_swap([2])

    assert captured == [1]  # the captured value never mutates under the caller
    assert swap.current() == [2]


def test_on_swap_fires_once_per_applied_swap_only() -> None:
    idle = {"v": False}
    seen: list[str] = []
    swap: IdleGatedSwap[str] = IdleGatedSwap("a", is_idle=lambda: idle["v"], on_swap=seen.append)

    swap.request_swap("b")  # deferred -> no callback yet
    assert seen == []

    idle["v"] = True
    swap.current()  # deferred swap lands here -> one callback
    swap.current()  # nothing pending -> no further callback

    assert seen == ["b"]


# --- ReloadablePhraseSnapper -------------------------------------------------------


def test_reloadable_snapper_satisfies_the_phrase_matcher_port() -> None:
    snapper = ReloadablePhraseSnapper(PhraseSnapper(INDEX), is_idle=lambda: True)

    assert isinstance(snapper, PhraseMatcher)
    assert isinstance(PhraseSnapper(INDEX), PhraseMatcher)  # the frozen domain one too


def test_snap_delegates_to_the_live_index() -> None:
    snapper = ReloadablePhraseSnapper(PhraseSnapper(INDEX), is_idle=lambda: True)

    result = snapper.snap("texaco request rejoin")

    assert result.decision is SnapDecision.SNAPPED
    assert result.text == "Texaco request rejoin"


def test_reload_while_idle_swaps_the_index_and_reports_the_count() -> None:
    counts: list[int] = []
    snapper = ReloadablePhraseSnapper(
        PhraseSnapper(INDEX), is_idle=lambda: True, on_reload=counts.append
    )

    applied = snapper.reload(OTHER_INDEX)

    assert applied is True
    assert counts == [len(OTHER_INDEX)]
    # The new index is live: a phrase from it now snaps, one from the old index does not.
    assert snapper.snap("colt request startup").decision is SnapDecision.SNAPPED
    assert snapper.phrase_index == tuple(OTHER_INDEX)


def test_reload_while_recording_is_deferred_until_idle() -> None:
    recording = {"v": True}
    counts: list[int] = []
    snapper = ReloadablePhraseSnapper(
        PhraseSnapper(INDEX),
        is_idle=lambda: not recording["v"],
        on_reload=counts.append,
    )

    applied = snapper.reload(OTHER_INDEX)

    assert applied is False  # never swap mid-utterance
    assert counts == []
    # Still the old index while recording.
    assert snapper.snap("texaco request rejoin").decision is SnapDecision.SNAPPED
    assert snapper.snap("colt request startup").decision is not SnapDecision.SNAPPED

    recording["v"] = False  # idle: the next snap applies the staged index
    assert snapper.snap("colt request startup").decision is SnapDecision.SNAPPED
    assert counts == [len(OTHER_INDEX)]


def test_reload_to_an_empty_index_makes_the_snapper_a_no_op() -> None:
    snapper = ReloadablePhraseSnapper(PhraseSnapper(INDEX), is_idle=lambda: True)

    snapper.reload([])

    result = snapper.snap("texaco request rejoin")
    assert result.decision is SnapDecision.RAW
    assert result.text == "texaco request rejoin"
