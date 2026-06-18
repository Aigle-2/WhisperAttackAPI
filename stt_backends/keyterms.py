"""Speech-to-text keyterm vocabulary.

The pure model (constants, budget value objects, and the budgeting function) now
lives in :mod:`vaivox.domain.vocabulary.keyterms` and is re-exported here for
backward compatibility. Loading the generated VAICOM vocabulary from disk is an
infrastructure concern and stays in this module until Phase 3 moves it.
"""

import logging
from pathlib import Path

from vaivox.domain.vocabulary.keyterms import (
    DEFAULT_DCS_KEYTERMS,
    DEFAULT_STT_KEYTERM_SOURCES,
    PHONETIC_ALPHABET,
    BudgetedKeyterms,
    KeytermBudget,
    apply_keyterm_budget,
)

VAICOM_KEYTERMS_FILE = "vaicom_keyterms.txt"

__all__ = [
    "DEFAULT_DCS_KEYTERMS",
    "DEFAULT_STT_KEYTERM_SOURCES",
    "PHONETIC_ALPHABET",
    "BudgetedKeyterms",
    "KeytermBudget",
    "apply_keyterm_budget",
    "load_vaicom_keyterms",
]


def load_vaicom_keyterms() -> list[str]:
    """
    Load generated VAICOM/DCS command vocabulary.
    """
    keyterm_file = Path(__file__).with_name(VAICOM_KEYTERMS_FILE)
    if not keyterm_file.is_file():
        logging.warning("VAICOM keyterm source file was not found: %s", keyterm_file)
        return []

    try:
        with open(keyterm_file, "r", encoding="utf-8") as file:
            return [
                line.strip() for line in file
                if line.strip() and not line.lstrip().startswith("#")
            ]
    except OSError as error:
        logging.warning("Failed to load VAICOM keyterm source file '%s': %s", keyterm_file, error)
        return []
