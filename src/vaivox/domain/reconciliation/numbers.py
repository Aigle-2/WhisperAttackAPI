"""Convert spoken number words to digits and separate joined numeric tokens.

Wraps the pure ``text2digits`` library; no I/O, so it is safe for the domain.
"""

from __future__ import annotations

import re

from text2digits import text2digits

_TEXT_TO_DIGITS = text2digits.Text2Digits()


def words_to_digits(text: str) -> str:
    """Convert number words to digits and split joined numeric runs.

    Spoken numbers (``"two seven zero"``) become digits (``"270"``); hyphens
    between digits and leading-zero runs are separated so each digit stands alone.

    Args:
        text: The text whose number words should be converted.

    Returns:
        The text with number words converted and numeric runs separated.
    """
    converted: str = _TEXT_TO_DIGITS.convert(text)
    converted = re.sub(r"(?<=\d)-(?=\d)", " ", converted)
    return re.sub(r"\b0\d+\b", lambda match: " ".join(match.group()), converted)
