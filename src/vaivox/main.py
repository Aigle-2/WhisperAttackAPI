"""VAIVOX bootstrap — the single application entry point.

Wired as the ``vaivox`` console script (``pyproject.toml``) and as the PyInstaller
build target. It resolves paths, configures logging, takes the single-instance lock,
and runs the windowed app built by the composition root. Heavy imports are deferred
into :func:`main` so importing this module never pulls in the UI stack.
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


def _ensure_src_on_path() -> None:
    """Make the in-repo ``src/`` and repo root importable when run from source.

    ``src/`` exposes the ``vaivox`` package; the repo root exposes ``tools/`` — the VAICOM
    vocabulary generator (ADR-0005) that the background ``RefreshVocabulary`` adapter imports
    lazily (``from tools import generate_vaicom_keyterms``). The ``vaivox`` console script only
    puts the package directory on ``sys.path``, so without the repo root the generator reports
    "generator unavailable" from a source run. A frozen build ships neither directory (the
    ``is_dir`` guard skips both) and degrades to the generic seed as designed.
    """
    here = Path(__file__).resolve()
    # parents[1] = .../src (the vaivox package); parents[2] = repo root (holds tools/).
    for path in (here.parents[1], here.parents[2]):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _resolve_app_path() -> str:
    """Return the directory holding the bundled assets and default configuration."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return str(Path(__file__).resolve().parents[2])


def _resolve_app_data_dir(data_dir_name: str) -> str:
    """Return (creating if needed) the per-user data directory for overrides/logs."""
    local_appdata = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    app_data_dir = os.path.join(local_appdata, data_dir_name)
    os.makedirs(app_data_dir, exist_ok=True)
    return app_data_dir


def _start_logging(app_data_dir: str, log_file_name: str) -> None:
    """Start file logging into the per-user data directory."""
    log_file = os.path.join(app_data_dir, log_file_name)
    logging.basicConfig(
        filename=log_file,
        filemode="w",
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logging.getLogger().setLevel(logging.INFO)


def main() -> None:
    """Run the application under a single-instance lock."""
    _ensure_src_on_path()

    from pid import PidFile, PidFileError

    from vaivox.infrastructure.config.identity import VAIVOX
    from vaivox.infrastructure.ui.app import VaivoxApp, show_error_dialog

    app_path = _resolve_app_path()
    app_data_dir = _resolve_app_data_dir(VAIVOX.data_dir_name)
    _start_logging(app_data_dir, VAIVOX.log_file_name)

    lock_file = os.path.join(app_data_dir, VAIVOX.instance_lock_name)
    try:
        with PidFile(lock_file):
            app = VaivoxApp(app_path, app_data_dir)
            app.run()
    except PidFileError:
        # Another instance already holds the lock.
        show_error_dialog(f"{VAIVOX.name} is already running")
    except Exception as error:
        trace = traceback.format_exc()
        _LOGGER.error("Server error: %s\n\n%s", error, trace)
        show_error_dialog(f"Unexpected server error: {error}")


if __name__ == "__main__":
    main()
