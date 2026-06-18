"""Speech-to-text keyterm vocabulary.

The pure model (constants, budget value objects, and the budgeting function) lives in
:mod:`vaivox.domain.vocabulary.keyterms`; loading the generated VAICOM vocabulary
from disk lives in :mod:`vaivox.infrastructure.vocabulary.vaicom_keyterms`. Both are
re-exported here for backward compatibility while the migration completes.
"""

from vaivox.domain.vocabulary.keyterms import (
    DEFAULT_DCS_KEYTERMS,
    DEFAULT_STT_KEYTERM_SOURCES,
    PHONETIC_ALPHABET,
    BudgetedKeyterms,
    KeytermBudget,
    apply_keyterm_budget,
)
from vaivox.infrastructure.vocabulary.vaicom_keyterms import (
    VAICOM_KEYTERMS_FILE,
    load_vaicom_keyterms,
)

__all__ = [
    "DEFAULT_DCS_KEYTERMS",
    "DEFAULT_STT_KEYTERM_SOURCES",
    "PHONETIC_ALPHABET",
    "VAICOM_KEYTERMS_FILE",
    "BudgetedKeyterms",
    "KeytermBudget",
    "apply_keyterm_budget",
    "load_vaicom_keyterms",
]
