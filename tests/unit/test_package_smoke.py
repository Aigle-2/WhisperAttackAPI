"""Smoke test: the vaivox package and every scaffolded subpackage import cleanly."""

from __future__ import annotations

import importlib
import pkgutil

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
