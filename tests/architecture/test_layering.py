"""Enforce ADR-0001's hexagonal dependency rule by running the import-linter contracts.

The contracts live in ``pyproject.toml`` under ``[tool.importlinter]``. They are run
in-process here (pytest puts ``src`` on ``sys.path`` via the ``pythonpath`` setting),
and also as a standalone ``lint-imports`` step in CI.
"""

from __future__ import annotations

from pathlib import Path

from importlinter.cli import EXIT_STATUS_SUCCESS, lint_imports

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _PROJECT_ROOT / "pyproject.toml"


def test_import_linter_contracts_hold() -> None:
    """Every import-linter contract must pass for the ``vaivox`` package tree."""
    exit_status = lint_imports(config_filename=str(_CONFIG), no_cache=True)
    assert exit_status == EXIT_STATUS_SUCCESS
