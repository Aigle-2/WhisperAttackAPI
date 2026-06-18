"""Load the generated VAICOM/DCS command vocabulary from disk.

This is the infrastructure side of the vocabulary: the pure model lives in
:mod:`vaivox.domain.vocabulary.keyterms`, while reading the generated file is an I/O
concern and stays here. Phase 4 (ADR-0005) replaces the bundled file with
auto-discovery + background generation; this loader keeps parity with the legacy
``stt_backends`` location until then.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

VAICOM_KEYTERMS_FILE = "vaicom_keyterms.txt"


def _candidate_paths() -> list[Path]:
    """Return the ordered locations to search for the keyterm file.

    Covers the PyInstaller bundle (``sys._MEIPASS``) and the in-repo source layout,
    matching where ``build_exe.ps1`` ships the file today.

    Returns:
        Candidate paths in priority order.
    """
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "stt_backends" / VAICOM_KEYTERMS_FILE)
    repo_root = Path(__file__).resolve().parents[4]
    candidates.append(repo_root / "stt_backends" / VAICOM_KEYTERMS_FILE)
    return candidates


def load_vaicom_keyterms() -> list[str]:
    """Load generated VAICOM/DCS command vocabulary.

    Returns:
        The non-comment, non-blank lines of the keyterm file, or an empty list when
        the file is missing or unreadable (logged as a warning, never raised).
    """
    for path in _candidate_paths():
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
            _LOGGER.warning("Failed to load VAICOM keyterm source file '%s': %s", path, error)
            return []

    _LOGGER.warning("VAICOM keyterm source file was not found: %s", VAICOM_KEYTERMS_FILE)
    return []
