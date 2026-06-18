"""Unit and characterization tests for the reconciliation domain.

The ``clean_transcription`` / ``reconcile`` expectations are golden values captured
from the original ``whisper_server`` implementation before extraction, so they pin
behavior parity (the migration plan's Phase 2 risk note).
"""

from __future__ import annotations

import pytest

from vaivox.domain.reconciliation.fuzzy import correct_dcs_and_phonetics_separately
from vaivox.domain.reconciliation.model import ReconciliationResult
from vaivox.domain.reconciliation.normalization import (
    normalize_unicode,
    replace_word_mappings,
    strip_punctuation,
)
from vaivox.domain.reconciliation.numbers import words_to_digits
from vaivox.domain.reconciliation.pipeline import clean_transcription, reconcile
from vaivox.domain.reconciliation.spelled_codes import compact_spelled_codes

PHONETIC_ALPHABET = [
    "Alpha",
    "Bravo",
    "Charlie",
    "Delta",
    "Echo",
    "Foxtrot",
    "Golf",
    "Hotel",
    "India",
    "Juliet",
    "Kilo",
    "Lima",
    "Mike",
    "November",
    "Oscar",
    "Papa",
    "Quebec",
    "Romeo",
    "Sierra",
    "Tango",
    "Uniform",
    "Victor",
    "Whiskey",
    "X-ray",
    "Yankee",
    "Zulu",
]
FUZZY_WORDS = ["Kobuleti", "Senaki", "Krymsk", "Texaco"]
WORD_MAPPINGS = {"inter": "Enter", "wilco roger": "wilco"}


# --- normalization ---------------------------------------------------------
def test_normalize_unicode_trims_and_composes() -> None:
    # "cafe" + U+0301 (combining acute) must NFC-normalize to precomposed U+00E9.
    decomposed_input = "  cafe" + chr(0x301) + "  "
    composed_expected = "caf" + chr(0xE9)
    assert normalize_unicode(decomposed_input) == composed_expected


def test_replace_word_mappings_is_case_insensitive_and_word_bounded() -> None:
    assert replace_word_mappings(WORD_MAPPINGS, "INTER and inter") == "Enter and Enter"
    assert replace_word_mappings(WORD_MAPPINGS, "wilco roger out") == "wilco out"
    assert replace_word_mappings(WORD_MAPPINGS, "winter") == "winter"


def test_strip_punctuation_removes_marks_and_collapses_whitespace() -> None:
    assert strip_punctuation("Overlord!!   bogey??") == "Overlord bogey"


# --- numbers ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("set heading two seven zero", "set heading 270"),
        ("button five", "button 5"),
        ("waypoint 3-4", "waypoint 3 4"),
        ("squawk 0123", "squawk 0 1 2 3"),
    ],
)
def test_words_to_digits(raw: str, expected: str) -> None:
    assert words_to_digits(raw) == expected


# --- spelled codes ---------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("request U L M B weather and I F F", "request ULMB weather and IFF"),
        ("tune U-L-M-B then E.S.N.J and T-V", "tune ULMB then ESNJ and TV"),
        ("A B C D E F G", "A B C D E F G"),
    ],
)
def test_compact_spelled_codes(raw: str, expected: str) -> None:
    assert compact_spelled_codes(raw) == expected


# --- fuzzy -----------------------------------------------------------------
def test_fuzzy_snaps_long_mistranscribed_token() -> None:
    assert (
        correct_dcs_and_phonetics_separately("kobuletti tower", FUZZY_WORDS, PHONETIC_ALPHABET)
        == "Kobuleti tower"
    )


def test_fuzzy_leaves_short_tokens_untouched() -> None:
    # "alfa" (4) and "bravo" (5) are below the six-character minimum.
    assert (
        correct_dcs_and_phonetics_separately("alfa bravo", FUZZY_WORDS, PHONETIC_ALPHABET)
        == "alfa bravo"
    )


def test_fuzzy_snaps_to_phonetic_alphabet() -> None:
    assert (
        correct_dcs_and_phonetics_separately("novemberr inbound", FUZZY_WORDS, PHONETIC_ALPHABET)
        == "November inbound"
    )


def test_fuzzy_abstains_below_threshold() -> None:
    assert (
        correct_dcs_and_phonetics_separately("texako request", FUZZY_WORDS, PHONETIC_ALPHABET)
        == "texako request"
    )


# --- pipeline (golden characterization) ------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Texaco, request rejoin.  ", "Texaco request rejoin"),
        ("tune U L M B and I F F", "tune ULMB and IFF"),
        ("set heading two seven zero", "set heading 270"),
        ("contact on button five", "contact on button 5"),
        ("frequency one two four point five", "frequency 124 .5"),
        ("squawk 0123", "squawk 0 1 2 3"),
        ("go to waypoint 3-4", "go to waypoint 3 4"),
        ("inter the pattern", "Enter the pattern"),
        ("Overlord!! bogey-dope??", "Overlord bogey-dope"),
        ("note request startup", "note request startup"),
    ],
)
def test_clean_transcription_golden(raw: str, expected: str) -> None:
    assert clean_transcription(raw, WORD_MAPPINGS) == expected


def test_reconcile_returns_staged_result() -> None:
    result = reconcile("kobuletti tower", {}, FUZZY_WORDS, PHONETIC_ALPHABET)

    assert isinstance(result, ReconciliationResult)
    assert result.raw_text == "kobuletti tower"
    assert result.cleaned_text == "kobuletti tower"
    assert result.command_text == "Kobuleti tower"
