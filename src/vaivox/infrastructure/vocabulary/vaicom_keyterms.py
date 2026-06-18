"""Load locally-generated VAICOM/DCS command vocabulary from disk.

VAICOM-derived vocabulary is **not** shipped with VAIVOX (ADR-0005): redistributing
data derived from a VAICOM install is a licensing grey zone. Instead the generator
(``tools/generate_vaicom_keyterms.py``) writes ``vaicom_keyterms.txt`` into the
per-user VAIVOX data directory, and this loader reads it from there. Until that file
exists VAIVOX runs on the generic, non-VAICOM seed
(:data:`vaivox.domain.vocabulary.keyterms.DEFAULT_DCS_KEYTERMS` + the phonetic
alphabet), so there is never a hard dependency on a generated file.

The pure model lives in :mod:`vaivox.domain.vocabulary.keyterms`; reading the file is
this infrastructure concern.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

VAICOM_KEYTERMS_FILE = "vaicom_keyterms.txt"

#: Optional explicit override pointing at a generated keyterm file.
VAICOM_KEYTERMS_ENV = "VAIVOX_VAICOM_KEYTERMS"


def _candidate_paths(data_dir: str | None) -> list[Path]:
    """Return the ordered locations to search for the generated keyterm file.

    Args:
        data_dir: The per-user data directory generation writes into, if known.

    Returns:
        Candidate paths in priority order (env override first, then the data dir).
    """
    candidates: list[Path] = []
    override = os.getenv(VAICOM_KEYTERMS_ENV, "").strip()
    if override:
        candidates.append(Path(override))
    if data_dir:
        candidates.append(Path(data_dir) / VAICOM_KEYTERMS_FILE)
    return candidates


def load_vaicom_keyterms(data_dir: str | None = None) -> list[str]:
    """Load locally-generated VAICOM/DCS command vocabulary.

    Args:
        data_dir: The per-user VAIVOX data directory the generator writes into. When
            ``None`` only the env override is consulted.

    Returns:
        The non-comment, non-blank lines of the keyterm file, or an empty list when no
        generated file is present (logged at debug level, never raised). An empty list
        is normal before the first generation — the generic seed covers the gap.
    """
    for path in _candidate_paths(data_dir):
        if not path.is_file():
            continue
        try:
            with open(path, encoding="utf-8") as file:
                return [
                    line.strip()
                    for line in file
                    if line.strip() and not line.lstrip().startswith("#")
                ]
        except OSError as error:
            _LOGGER.warning("Failed to load VAICOM keyterm file '%s': %s", path, error)
            return []

    _LOGGER.debug("No generated VAICOM keyterm file found; using the generic seed.")
    return []
