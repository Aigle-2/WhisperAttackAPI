"""Load the locally-generated phrase index from disk (Axis B, ADR-0011 / ADR-0005).

The conservative phrase snapper (:mod:`vaivox.domain.reconciliation.snapper`) scores a
reconciled command against an index of valid VAICOM command phrases. That index is
**not** shipped with VAIVOX, for the same reason the keyterms are not (ADR-0005):
redistributing data derived from a VAICOM install is a licensing grey zone. Instead the
generator writes ``phrase_index.txt`` (one valid command phrase per line) into the
per-user VAIVOX data directory under %LOCALAPPDATA% VAIVOX, and this loader reads it from
there. The index is **frozen per session** (ADR-0009 does not hot-swap it).

Until that file exists the loader returns an empty list, which makes the snapper a no-op
(every utterance is sent raw) — so there is never a hard dependency on a generated file
and behaviour parity is preserved on a fresh install.

This mirrors :mod:`vaivox.infrastructure.vocabulary.vaicom_keyterms`: same data-dir
search, same optional env override, same graceful empty when absent. Generating the
index from a real VAICOM install is an ADR-0011 follow-up (it needs that install) and is
out of scope here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

PHRASE_INDEX_FILE = "phrase_index.txt"

#: Optional explicit override pointing at a generated phrase-index file.
PHRASE_INDEX_ENV = "VAIVOX_PHRASE_INDEX"


def _candidate_paths(data_dir: str | None) -> list[Path]:
    """Return the ordered locations to search for the generated phrase index.

    Args:
        data_dir: The per-user data directory generation writes into, if known.

    Returns:
        Candidate paths in priority order (env override first, then the data dir).
    """
    candidates: list[Path] = []
    override = os.getenv(PHRASE_INDEX_ENV, "").strip()
    if override:
        candidates.append(Path(override))
    if data_dir:
        candidates.append(Path(data_dir) / PHRASE_INDEX_FILE)
    return candidates


def load_phrase_index(data_dir: str | None = None) -> list[str]:
    """Load the locally-generated phrase index of valid command phrases.

    Args:
        data_dir: The per-user VAIVOX data directory the generator writes into. When
            ``None`` only the env override is consulted.

    Returns:
        The non-comment, non-blank lines of the phrase-index file, or an empty list when
        no generated file is present (logged at debug level, never raised). An empty list
        is normal before the first generation — it makes the snapper a no-op.
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
            _LOGGER.warning("Failed to load phrase-index file '%s': %s", path, error)
            return []

    _LOGGER.debug("No generated phrase-index file found; the snapper is a no-op.")
    return []
