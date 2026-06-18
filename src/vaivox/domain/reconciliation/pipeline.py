"""The reconciliation pipeline: clean a raw transcript and fuzzy-correct it.

This composes the pure reconciliation steps in the exact order the legacy
``whisper_server`` applied them, preserving behavior while making the whole
path testable with no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vaivox.domain.reconciliation.fuzzy import correct_dcs_and_phonetics_separately
from vaivox.domain.reconciliation.model import ReconciliationResult
from vaivox.domain.reconciliation.normalization import (
    normalize_unicode,
    replace_word_mappings,
    strip_punctuation,
)
from vaivox.domain.reconciliation.numbers import words_to_digits
from vaivox.domain.reconciliation.spelled_codes import compact_spelled_codes

_DEFAULT_FUZZY_THRESHOLD = 85


def clean_transcription(text: str, word_mappings: Mapping[str, str]) -> str:
    """Run the deterministic cleanup chain (parity with ``custom_cleanup_text``).

    The order is: NFC normalize, apply word mappings, convert number words,
    strip punctuation/whitespace, then compact spelled codes.

    Args:
        text: The raw transcription text.
        word_mappings: The configured alias-to-replacement mappings.

    Returns:
        The cleaned transcription text.
    """
    text = normalize_unicode(text)
    text = replace_word_mappings(word_mappings, text)
    text = words_to_digits(text)
    text = strip_punctuation(text)
    return compact_spelled_codes(text)


def reconcile(
    text: str,
    word_mappings: Mapping[str, str],
    fuzzy_words: Sequence[str],
    phonetic_alphabet: Sequence[str],
    dcs_threshold: int = _DEFAULT_FUZZY_THRESHOLD,
    phonetic_threshold: int = _DEFAULT_FUZZY_THRESHOLD,
) -> ReconciliationResult:
    """Clean a raw transcript and fuzzy-correct it into a command.

    Args:
        text: The raw transcription text.
        word_mappings: The configured alias-to-replacement mappings.
        fuzzy_words: Candidate DCS callsigns/keywords for fuzzy correction.
        phonetic_alphabet: The NATO phonetic-alphabet words.
        dcs_threshold: Minimum score (0-100) to accept a DCS fuzzy match.
        phonetic_threshold: Minimum score (0-100) to accept a phonetic match.

    Returns:
        A :class:`ReconciliationResult` capturing the raw, cleaned, and command text.
    """
    cleaned = clean_transcription(text, word_mappings)
    command = correct_dcs_and_phonetics_separately(
        cleaned,
        fuzzy_words,
        phonetic_alphabet,
        dcs_threshold,
        phonetic_threshold,
    )
    return ReconciliationResult(raw_text=text, cleaned_text=cleaned, command_text=command)
