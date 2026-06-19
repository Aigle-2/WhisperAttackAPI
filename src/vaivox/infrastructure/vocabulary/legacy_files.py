"""Legacy flat vocabulary file reader.

This adapter exists only for one-shot migration/upgrade compatibility. The runtime
pipeline reads structured JSONL through ``VocabularyRepository``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


def load_legacy_vocabulary(locations: Sequence[str]) -> tuple[dict[str, str], list[str]]:
    """Load merged legacy word mappings and fuzzy words from ``locations``.

    Args:
        locations: Directories to scan in priority order. Later mappings override earlier
            mappings; fuzzy words are appended in order.

    Returns:
        ``(word_mappings, fuzzy_words)`` parsed from any existing legacy files.
    """
    word_mappings: dict[str, str] = {}
    fuzzy_words: list[str] = []
    for location in locations:
        directory = Path(location)
        word_mappings.update(_load_word_mappings(directory / "word_mappings.txt"))
        fuzzy_words.extend(_load_fuzzy_words(directory / "fuzzy_words.txt"))
    return word_mappings, fuzzy_words


def _load_word_mappings(path: Path) -> dict[str, str]:
    mappings: dict[str, str] = {}
    if not path.is_file():
        return mappings
    try:
        with open(path, encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("=", maxsplit=1)
                if len(parts) != 2:
                    continue
                aliases, target = parts
                replacement = target.strip()
                for raw_alias in aliases.split(";"):
                    alias = raw_alias.strip()
                    if alias and replacement:
                        mappings[alias] = replacement
    except OSError as error:
        _LOGGER.warning("Failed to read legacy word mappings '%s': %s", path, error)
    return mappings


def _load_fuzzy_words(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        with open(path, encoding="utf-8") as file:
            return [line.strip() for line in file if line.strip() and not line.startswith("#")]
    except OSError as error:
        _LOGGER.warning("Failed to read legacy fuzzy words '%s': %s", path, error)
        return []


__all__ = ["load_legacy_vocabulary"]
