"""Unicode, word-mapping, and punctuation normalization of transcribed text.

These are the deterministic, vocabulary-independent cleanup steps; they are pure
functions so the reconciliation pipeline can be exercised with no I/O.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping


def normalize_unicode(text: str) -> str:
    """Trim surrounding whitespace and apply Unicode NFC normalization.

    Args:
        text: The raw transcription text.

    Returns:
        The trimmed, NFC-normalized text.
    """
    return unicodedata.normalize("NFC", text.strip())


def replace_word_mappings(word_mappings: Mapping[str, str], text: str) -> str:
    """Replace each mapped alias with its replacement.

    Matching is case-insensitive and constrained to whole words.

    Args:
        word_mappings: A mapping of alias to replacement word.
        text: The text in which to apply the replacements.

    Returns:
        The text with every alias replaced by its mapped value.
    """
    for word, replacement in word_mappings.items():
        pattern = rf"\b{re.escape(word)}\b"
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def strip_punctuation(text: str) -> str:
    """Remove stray punctuation and collapse runs of whitespace.

    Args:
        text: The text to clean.

    Returns:
        The text with punctuation removed and whitespace collapsed to single spaces.
    """
    text = re.sub(r"([^\w\d\s])*(?![\w\-\w])(?![^-])?", " ", text)
    return re.sub(r"\s+", " ", text).strip()
