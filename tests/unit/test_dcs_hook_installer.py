"""Unit tests for the self-healing DCS panel hook installer (ADR-0012)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vaivox.infrastructure.dcs import hook_installer
from vaivox.infrastructure.dcs.hook_installer import (
    DcsHookInstaller,
    _steam_dcs_roots_from_vdf,
    discover_panel_path,
    is_dcs_running,
    render_hook,
)

_STOCK = "-- stock panel\nfunction clearOtherMenu() end\nfunction addOtherCommand(n, a, p) end\n"


def _panel(tmp_path: Path, content: str = _STOCK) -> Path:
    path = tmp_path / "RadioCommandDialogsPanel.lua"
    path.write_text(content, encoding="utf-8")
    return path


def test_render_hook_includes_port_type_and_markers() -> None:
    lua = render_hook(33493)
    assert "VAIVOX_F10_HOOK v8" in lua
    assert "BEGIN" in lua and "END" in lua
    assert "33493" in lua
    assert "vaivox.f10menu" in lua
    assert "protocol = 2" in lua
    assert "session = session" in lua
    assert "revision = revision" in lua
    assert "aircraft = aircraft" in lua
    assert "entries = entries" in lua
    assert "path = append_path(path, nil)" in lua
    assert "LoGetSelfData" in lua


def test_render_hook_republishes_an_unchanged_revision_as_a_heartbeat() -> None:
    lua = render_hook(33493)

    assert "local heartbeat_seconds = 5" in lua
    assert "if advance_revision ~= false then revision = revision + 1 end" in lua
    assert 'publish("heartbeat", false)' in lua


def test_render_hook_uses_the_dcs_base_namespace_for_standard_functions() -> None:
    """Regression for the live DCS error: bare ``pcall`` is nil after ``module(...)``."""
    lua = render_hook(33493)

    assert "base.pcall" in lua
    assert "base.type" in lua
    assert re.search(r"(?<![\w.])pcall\(", lua) is None
    assert re.search(r"(?<![\w.])type\(", lua) is None


def test_render_hook_scans_the_same_menu_tree_vaicom_exports() -> None:
    lua = render_hook(33493)

    assert "data and data.menuOther" in lua
    assert "command.actionIndex" in lua
    assert "scan_node(item.submenu" in lua
    assert "base.vaicom.init.start = function" in lua
    assert "Gui.AddUpdateCallback(poll_menu)" in lua


def test_render_hook_does_not_replace_callbacks_dcs_may_have_cached() -> None:
    lua = render_hook(33493)

    assert "clearOtherMenu = function" not in lua
    assert "addOtherCommand = function" not in lua


def test_install_then_idempotent_no_churn(tmp_path: Path) -> None:
    panel = _panel(tmp_path)
    installer = DcsHookInstaller(panel, 33493)

    assert installer.ensure_installed() == "installed"
    after_first = panel.read_text(encoding="utf-8")
    assert installer.ensure_installed() == "already current"
    assert panel.read_text(encoding="utf-8") == after_first  # second run does not rewrite
    assert "-- stock panel" in after_first  # stock content preserved


def test_panel_not_found(tmp_path: Path) -> None:
    assert DcsHookInstaller(tmp_path / "missing.lua", 33493).ensure_installed() == "panel not found"


def test_replaces_an_older_version_block(tmp_path: Path) -> None:
    older = _STOCK + "\n-- VAIVOX_F10_HOOK v0 BEGIN\nstale junk\n-- VAIVOX_F10_HOOK v0 END\n"
    panel = _panel(tmp_path, older)

    assert DcsHookInstaller(panel, 33493).ensure_installed() == "updated"

    text = panel.read_text(encoding="utf-8")
    assert "v0 BEGIN" not in text
    assert text.count("VAIVOX_F10_HOOK") == 2  # exactly one block (BEGIN + END markers)


def test_changing_port_reinstalls(tmp_path: Path) -> None:
    panel = _panel(tmp_path)
    DcsHookInstaller(panel, 33493).ensure_installed()

    assert DcsHookInstaller(panel, 40000).ensure_installed() == "updated"
    text = panel.read_text(encoding="utf-8")
    assert "40000" in text
    assert "33493" not in text


def test_discover_panel_path(tmp_path: Path) -> None:
    assert discover_panel_path(None) is None
    assert discover_panel_path(str(tmp_path)) is None  # no panel under this root

    panel = tmp_path / "Scripts" / "UI" / "RadioCommandDialogPanel" / "RadioCommandDialogsPanel.lua"
    panel.parent.mkdir(parents=True)
    panel.write_text("x", encoding="utf-8")
    assert discover_panel_path(str(tmp_path)) == panel


def test_steam_dcs_roots_prioritizes_the_library_owning_dcs() -> None:
    # Two libraries, both with a DCSWorld folder; only F: owns the DCS app id (223750), so
    # it must be tried first even though C: appears earlier in the file.
    vdf = (
        '"libraryfolders"\n{\n'
        '  "0"\n  {\n    "path"  "C:\\\\Jeux"\n'
        '    "apps"\n    {\n      "730"  "1"\n    }\n  }\n'
        '  "1"\n  {\n    "path"  "F:\\\\SteamLibrary"\n'
        '    "apps"\n    {\n      "223750"  "999"\n    }\n  }\n'
        "}\n"
    )

    roots = _steam_dcs_roots_from_vdf(vdf)

    assert roots[0] == str(Path("F:\\SteamLibrary") / "steamapps" / "common" / "DCSWorld")
    assert str(Path("C:\\Jeux") / "steamapps" / "common" / "DCSWorld") in roots


def test_is_dcs_running(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    monkeypatch.setattr(
        hook_installer.subprocess,
        "run",
        lambda *a, **k: _Result("DCS.exe   1234 Console   1   2,000 K\n"),
    )
    assert is_dcs_running() is True

    monkeypatch.setattr(
        hook_installer.subprocess,
        "run",
        lambda *a, **k: _Result("INFO: No tasks are running.\n"),
    )
    assert is_dcs_running() is False

    def _boom(*a: object, **k: object) -> object:
        raise OSError("tasklist missing")

    monkeypatch.setattr(hook_installer.subprocess, "run", _boom)
    assert is_dcs_running() is False
