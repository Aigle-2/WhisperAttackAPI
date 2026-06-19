"""Unit tests for the conservative phrase snapper (Axis B, ADR-0011).

Exercises each band (snap / abstain / raw), the mandatory runner-up margin guard, the
empty-index no-op, and the structure of the near-miss output. Uses a small synthetic
phrase index so nothing VAICOM-derived is committed.
"""

from __future__ import annotations

import pytest

from vaivox.domain.reconciliation.snapper import (
    DEFAULT_HIGH,
    DEFAULT_LOW,
    DEFAULT_MARGIN,
    NearMiss,
    PhraseSnapper,
    SnapDecision,
    SnapResult,
    build_snapper,
)

INDEX = [
    "Texaco request rejoin",
    "Texaco request fuel",
    "Overlord bogey dope",
    "Springfield request startup",
    "Colt request startup",
]


def test_exact_phrase_snaps_to_itself() -> None:
    result = PhraseSnapper(INDEX).snap("texaco request rejoin")

    assert result.decision is SnapDecision.SNAPPED
    assert result.text == "Texaco request rejoin"  # original casing preserved
    assert result.candidate == "Texaco request rejoin"
    assert result.score == 100.0
    assert result.near_misses == ()


def test_high_confidence_near_miss_snaps_to_correct_phrase() -> None:
    # The eval's recoverable cases: leading filler, word split, misheard token.
    snapper = PhraseSnapper(INDEX)

    assert snapper.snap("uh Springfield request startup").text == "Springfield request startup"
    assert snapper.snap("colt request start up").text == "Colt request startup"
    for raw in ("uh Springfield request startup", "colt request start up"):
        assert snapper.snap(raw).decision is SnapDecision.SNAPPED


def test_spoken_compound_snaps_to_stored_single_token_phrase() -> None:
    snapper = PhraseSnapper(
        [
            "Place the Wheelblocks",
            "Pull the Blocks",
            "Ground Blocks Place",
            "Remove the Wheelblocks",
        ]
    )

    result = snapper.snap("place wheel blocks")

    assert result.decision is SnapDecision.SNAPPED
    assert result.text == "Place the Wheelblocks"
    assert result.score >= DEFAULT_HIGH


def test_hyphenated_transcript_snaps_to_space_separated_phrase() -> None:
    # Real operator evidence: Whisper transcribed "TACAN Air-to-Air"; the stored command is
    # "TACAN Air to Air". The hyphen used to drop token_sort_ratio to 75 (an abstain); folding
    # connector punctuation to spaces restores the exact match so it snaps cleanly.
    snapper = PhraseSnapper(["TACAN Air to Air", "TACAN Air refuel", "TACAN Oscar Alfa Lima"])

    result = snapper.snap("TACAN Air-to-Air")

    assert result.decision is SnapDecision.SNAPPED
    assert result.text == "TACAN Air to Air"  # original casing of the stored phrase
    assert result.score == 100.0


def test_mid_confidence_abstains_and_reports_near_miss() -> None:
    # A score in [LOW, HIGH): the snapper holds the text and emits a near-miss instead.
    snapper = PhraseSnapper(INDEX, high=99.0, low=50.0, margin=1.0)

    result = snapper.snap("texaco request rejon")  # ~95, below the inflated HIGH

    assert result.decision is SnapDecision.ABSTAINED
    assert result.text == "texaco request rejon"  # unchanged
    assert result.candidate == "Texaco request rejoin"
    assert result.near_misses  # populated
    assert all(isinstance(nm, NearMiss) for nm in result.near_misses)
    # Near-misses are sorted best-first and the top one is the candidate.
    assert result.near_misses[0].phrase == "Texaco request rejoin"
    scores = [nm.score for nm in result.near_misses]
    assert scores == sorted(scores, reverse=True)


def test_low_confidence_sends_raw_without_near_miss() -> None:
    result = PhraseSnapper(INDEX).snap("something completely unrelated zzz")

    assert result.decision is SnapDecision.RAW
    assert result.text == "something completely unrelated zzz"
    assert result.near_misses == ()


def test_margin_blocks_an_ambiguous_winner() -> None:
    # Two phrases share "Texaco request"; an ambiguous query scores both high. With a
    # large margin requirement the snapper must NOT snap (this is the wrong-match guard).
    snapper = PhraseSnapper(INDEX, high=50.0, low=10.0, margin=40.0)

    result = snapper.snap("texaco request")

    assert result.decision is SnapDecision.ABSTAINED
    assert result.text == "texaco request"  # never fires one of the two ambiguous phrases


def test_margin_allows_an_unambiguous_winner() -> None:
    # The same low HIGH, but an unambiguous query clears the margin and snaps.
    snapper = PhraseSnapper(INDEX, high=50.0, low=10.0, margin=40.0)

    result = snapper.snap("overlord bogey dope")

    assert result.decision is SnapDecision.SNAPPED
    assert result.text == "Overlord bogey dope"


def test_empty_index_is_a_no_op() -> None:
    result = PhraseSnapper([]).snap("texaco request rejoin")

    assert result == SnapResult(decision=SnapDecision.RAW, text="texaco request rejoin")
    assert result.candidate is None


@pytest.mark.parametrize("text", ["", "   ", "\t"])
def test_blank_input_is_raw(text: str) -> None:
    assert PhraseSnapper(INDEX).snap(text).decision is SnapDecision.RAW


def test_index_is_deduplicated_case_insensitively() -> None:
    snapper = PhraseSnapper(
        ["Texaco request rejoin", "texaco request rejoin", "  TEXACO REQUEST REJOIN  "]
    )

    assert snapper.phrase_index == ("Texaco request rejoin",)


def test_snap_is_deterministic() -> None:
    snapper = PhraseSnapper(INDEX)

    assert snapper.snap("colt request start up") == snapper.snap("colt request start up")


def test_build_snapper_uses_conservative_defaults() -> None:
    snapper = build_snapper(INDEX)

    # The defaults are the eval-calibrated conservative values (ADR-0011).
    assert (DEFAULT_HIGH, DEFAULT_LOW, DEFAULT_MARGIN) == (90.0, 60.0, 15.0)
    # A high-confidence near-miss snaps under the defaults; an ambiguous one does not.
    assert snapper.snap("uh Springfield request startup").decision is SnapDecision.SNAPPED
    assert snapper.snap("texaco request").decision is not SnapDecision.SNAPPED
