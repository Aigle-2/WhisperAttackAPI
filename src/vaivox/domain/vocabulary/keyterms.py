"""Vocabulary model for speech-to-text keyterm biasing.

Pure constants, value objects, and the budgeting function shared by every STT
adapter. Loading provider-specific or generated vocabulary from disk is an
infrastructure concern and lives outside the domain.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

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

DEFAULT_DCS_KEYTERMS = [
    "Enfield",
    "Springfield",
    "Uzi",
    "Colt",
    "Dodge",
    "Ford",
    "Chevy",
    "Pontiac",
    "Overlord",
    "Magic",
    "Wizard",
    "Focus",
    "Darkstar",
    "Texaco",
    "Arco",
    "Shell",
    "Axeman",
    "JTAC",
    "request startup",
    "request taxi",
    "request takeoff",
    "request rejoin",
    "bogey dope",
    "ready to copy",
]

DEFAULT_STT_KEYTERM_SOURCES = [
    "custom",
    "phonetic_alphabet",
    "fuzzy_words",
    "word_mapping_replacements",
    "dcs_default",
    "vaicom",
]


@dataclass(frozen=True)
class KeytermBudget:
    """Provider-side limits for vocabulary/context biasing.

    Attributes:
        max_terms: Maximum number of keyterms, or ``None`` for unlimited.
        max_term_chars: Maximum length of a single keyterm, or ``None``.
        max_total_chars: Maximum combined length of all keyterms, or ``None``.
    """

    max_terms: int | None = None
    max_term_chars: int | None = None
    max_total_chars: int | None = None


@dataclass(frozen=True)
class BudgetedKeyterms:
    """Keyterms after applying provider-side limits.

    Attributes:
        keyterms: The selected keyterms in caller priority order.
        skipped_too_long: Count of keyterms dropped for exceeding ``max_term_chars``.
        omitted_by_term_limit: Count dropped after reaching ``max_terms``.
        omitted_by_char_limit: Count dropped after reaching ``max_total_chars``.
    """

    keyterms: list[str]
    skipped_too_long: int = 0
    omitted_by_term_limit: int = 0
    omitted_by_char_limit: int = 0


def apply_keyterm_budget(keyterms: Iterable[str], budget: KeytermBudget) -> BudgetedKeyterms:
    """Apply count, per-term, and total-context limits without reordering.

    Args:
        keyterms: The candidate keyterms in caller priority order.
        budget: The provider-side limits to enforce.

    Returns:
        The budgeted selection together with per-reason omission counts.
    """
    selected: list[str] = []
    skipped_too_long = 0
    omitted_by_term_limit = 0
    omitted_by_char_limit = 0
    total_chars = 0

    for keyterm in keyterms:
        normalized_keyterm = keyterm.strip()
        if not normalized_keyterm:
            continue

        if budget.max_term_chars is not None and len(normalized_keyterm) > budget.max_term_chars:
            skipped_too_long += 1
            continue

        if budget.max_terms is not None and len(selected) >= budget.max_terms:
            omitted_by_term_limit += 1
            continue

        projected_chars = total_chars + len(normalized_keyterm)
        if selected:
            projected_chars += 2
        if budget.max_total_chars is not None and projected_chars > budget.max_total_chars:
            omitted_by_char_limit += 1
            continue

        selected.append(normalized_keyterm)
        total_chars = projected_chars

    return BudgetedKeyterms(
        keyterms=selected,
        skipped_too_long=skipped_too_long,
        omitted_by_term_limit=omitted_by_term_limit,
        omitted_by_char_limit=omitted_by_char_limit,
    )
