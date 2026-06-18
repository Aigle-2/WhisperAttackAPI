"""Smoke test: the vaivox package and every scaffolded subpackage import cleanly."""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path

import vaivox


def test_all_vaivox_modules_import() -> None:
    """Importing every module in the vaivox tree must succeed (no import errors)."""
    imported = {vaivox.__name__}
    for module_info in pkgutil.walk_packages(vaivox.__path__, prefix="vaivox."):
        importlib.import_module(module_info.name)
        imported.add(module_info.name)

    # The three hexagonal layers plus the bootstrap modules must all be present.
    for expected in (
        "vaivox.domain",
        "vaivox.application",
        "vaivox.infrastructure",
        "vaivox.composition",
        "vaivox.main",
    ):
        assert expected in imported, f"missing scaffolded module: {expected}"


def test_bootstrap_shim_exposes_tools_generator() -> None:
    """The bootstrap shim must put the repo root on sys.path so ``tools`` imports.

    The VAICOM vocabulary generator (ADR-0005) lives in ``tools/`` at the repo root, which
    the ``vaivox`` console script does not add to ``sys.path``. A regression here resurfaces
    as the background ``RefreshVocabulary`` adapter reporting "generator unavailable" from a
    source run (the ``from tools import ...`` import fails).
    """
    from vaivox import main

    repo_root = str(Path(main.__file__).resolve().parents[2])
    saved = list(sys.path)
    try:
        sys.path[:] = [path for path in sys.path if path != repo_root]
        main._ensure_src_on_path()
        assert repo_root in sys.path
        assert importlib.util.find_spec("tools") is not None
    finally:
        sys.path[:] = saved
