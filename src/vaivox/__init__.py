"""VAIVOX: turns push-to-talk speech into DCS radio commands (hexagonal core)."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _resolve_version() -> str:
    """Resolve the package version from pyproject-owned metadata."""
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject_path.is_file():
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project_version = pyproject.get("project", {}).get("version")
        if isinstance(project_version, str):
            return project_version

    try:
        return version("vaivox")
    except PackageNotFoundError:
        return "0+unknown"


__version__ = _resolve_version()
