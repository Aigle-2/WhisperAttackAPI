"""Compact spelled-out letter sequences into aviation code tokens."""

from __future__ import annotations

import re


def compact_spelled_codes(text: str, min_letters: int = 2, max_letters: int = 6) -> str:
    """Join runs of single spelled letters into uppercase code tokens.

    For example ``"U L M B"`` becomes ``"ULMB"``. Runs shorter than
    ``min_letters`` or longer than ``max_letters`` are left untouched.

    Args:
        text: The whitespace-tokenized transcription text.
        min_letters: Minimum run length (inclusive) eligible for compaction.
        max_letters: Maximum run length (inclusive) eligible for compaction.

    Returns:
        The text with qualifying single-letter runs joined into code tokens.
    """
    text = re.sub(r"(?<=\b[A-Za-z])[-./](?=[A-Za-z]\b)", " ", text)
    tokens = text.split()
    compacted_tokens: list[str] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if not re.fullmatch(r"[A-Za-z]", token):
            compacted_tokens.append(token)
            index += 1
            continue

        letters: list[str] = []
        end_index = index
        while end_index < len(tokens) and re.fullmatch(r"[A-Za-z]", tokens[end_index]):
            letters.append(tokens[end_index].upper())
            end_index += 1

        if min_letters <= len(letters) <= max_letters:
            compacted_tokens.append("".join(letters))
            index = end_index
            continue

        compacted_tokens.extend(tokens[index:end_index])
        index = end_index

    return " ".join(compacted_tokens)
