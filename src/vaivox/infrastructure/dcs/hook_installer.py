"""Install and self-heal the VAIVOX F10 hook in the DCS radio command panel (ADR-0012).

The executable ``ActionIndex`` lives only in the DCS command-dialog panel, so VAIVOX injects
a small Lua block at the end of
``<DCS>/Scripts/UI/RadioCommandDialogPanel/RadioCommandDialogsPanel.lua``. The block scans
the panel's lexical ``data.menuOther`` tree (the same source VAICOM exports as ``menuaux``)
on a throttled GUI callback and broadcasts current labels, submenu paths, and action indices
to VAIVOX's listener (:mod:`~vaivox.infrastructure.dcs.menu_listener`).

DCS overwrites this stock panel on a game update, and VAICOM rewrites it on launch, so the
block is **marker-guarded and re-applied on every VAIVOX startup**: :meth:`ensure_installed`
is idempotent (no write when already current) and strips any older block before appending the
current one — the user installs nothing manually after first setup.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from vaivox.infrastructure.dcs.menu_listener import DEFAULT_MENU_PORT

_LOGGER = logging.getLogger(__name__)

#: Bump when the Lua changes so :meth:`ensure_installed` replaces an older deployed block.
#: v6 scans the authoritative ``data.menuOther`` tree that VAICOM itself exports. DCS keeps
#: cached references to the original public menu callbacks, so replacing those functions at
#: the end of the panel (v5) did not observe missionCommands/MOOSE updates.
_HOOK_VERSION = "v6"

#: Matches any deployed VAIVOX block (any version) plus the blank lines before it, so a stale
#: or older-version block is removed cleanly before the current one is appended.
_BLOCK_RE = re.compile(
    r"\n*-- VAIVOX_F10_HOOK v\d+ BEGIN\b.*?-- VAIVOX_F10_HOOK v\d+ END[^\n]*\n?",
    re.DOTALL,
)

_HOOK_TEMPLATE = """-- VAIVOX_F10_HOOK {version} BEGIN  (auto-managed by VAIVOX; do not edit)
-- Publishes the live F10 menu to VAIVOX via UDP. The file mirror is diagnostic only;
-- runtime dispatch remains fail-closed until this process sends a live snapshot. ADR-0012.
local function _vaivox_write(name, content)
  if not (base and base.io and base.lfs and base.lfs.writedir) then return end
  base.pcall(function()
    local f = base.io.open(base.lfs.writedir() .. "Logs/" .. name, "w")
    if f then f:write(content); f:close() end
  end)
end

local function _vaivox_report(message, is_error)
  local rendered = "VAIVOX F10 hook: " .. base.tostring(message)
  _vaivox_write("vaivox_hook_status.txt", rendered)
  base.pcall(function()
    if base.env then
      if is_error and base.env.error then
        base.env.error(rendered)
      elseif base.env.info then
        base.env.info(rendered)
      end
    end
  end)
end

_vaivox_report("loading {version}", false)
local _vaivox_ok, _vaivox_err = base.pcall(function()
  local ok_j, JSON = base.pcall(base.require, "JSON")
  if not (ok_j and JSON) then _vaivox_report("JSON module unavailable", true); return end
  local ok_s, socket = base.pcall(base.require, "socket")
  local sock = nil
  if ok_s and socket then
    local ok_udp, candidate = base.pcall(function() return socket.udp() end)
    if ok_udp then sock = candidate end
    if sock then
      local ok_peer = base.pcall(function() sock:setpeername("127.0.0.1", {port}) end)
      if not ok_peer then sock = nil end
    end
  end

  local session = base.tostring({{}})
  local revision = 0
  local entries = {{}}

  local function append_path(path, name)
    local copied = {{}}
    for index, value in base.ipairs(path) do copied[index] = base.tostring(value) end
    if base.type(name) == "string" then base.table.insert(copied, name) end
    return copied
  end

  local function publish(phase)
    revision = revision + 1
    local ok_payload, payload = base.pcall(function()
      return JSON:encode({{
        type = "vaivox.f10menu",
        protocol = 2,
        session = session,
        revision = revision,
        phase = phase,
        entries = entries,
      }})
    end)
    if not ok_payload then
      _vaivox_report("JSON encode failed: " .. base.tostring(payload), true)
      return
    end
    if sock then base.pcall(function() sock:send(payload) end) end
    _vaivox_write("vaivox_f10_menu.json", payload)
  end

  local function scan_node(node, path, found)
    if base.type(node) ~= "table" then return end
    if base.type(node.items) == "table" then
      for _, item in base.ipairs(node.items) do
        if base.type(item) == "table" then
          local name = item.name
          local command = item.command
          if base.type(name) == "string" and base.type(command) == "table" and
             base.type(command.actionIndex) == "number" then
            base.table.insert(found, {{
              label = name,
              action_index = command.actionIndex,
              path = append_path(path, nil),
            }})
          end
          if base.type(item.submenu) == "table" then
            scan_node(item.submenu, append_path(path, name), found)
          end
        end
      end
    end
    if base.type(node.submenu) == "table" then
      scan_node(node.submenu, path, found)
    end
  end

  local last_fingerprint = nil
  local last_poll = nil
  local last_scan_error = nil
  local function scan_if_changed()
    local found = {{}}
    scan_node(data and data.menuOther, {{}}, found)
    local ok_fingerprint, fingerprint = base.pcall(function() return JSON:encode(found) end)
    if not ok_fingerprint then base.error(fingerprint) end
    if fingerprint ~= last_fingerprint then
      last_fingerprint = fingerprint
      entries = found
      publish("scan")
      _vaivox_report(
        "snapshot revision=" .. base.tostring(revision) ..
        " entries=" .. base.tostring(#entries) .. " session=" .. session,
        false
      )
    end
  end

  local function poll_menu()
    local ok_scan, scan_error = base.pcall(function()
      local now = nil
      if base.os and base.os.clock then
        now = base.os.clock()
      elseif base.Export and base.Export.LoGetModelTime then
        now = base.Export.LoGetModelTime()
      end
      if now ~= nil and last_poll ~= nil and now >= last_poll and now - last_poll < 0.5 then
        return
      end
      last_poll = now
      scan_if_changed()
    end)
    if not ok_scan then
      local rendered = base.tostring(scan_error)
      if rendered ~= last_scan_error then
        last_scan_error = rendered
        _vaivox_report("scan failed: " .. rendered, true)
      end
    end
  end

  local function install_poll()
    base.pcall(function() Gui.RemoveUpdateCallback(poll_menu) end)
    local ok_add, add_error = base.pcall(function() Gui.AddUpdateCallback(poll_menu) end)
    if not ok_add then
      _vaivox_report("scanner registration failed: " .. base.tostring(add_error), true)
      return
    end
    poll_menu()
  end

  local original_start = base.vaicom and base.vaicom.init and base.vaicom.init.start
  local original_stop = base.vaicom and base.vaicom.init and base.vaicom.init.stop
  if original_start then
    base.vaicom.init.start = function(self, ...)
      local result = original_start(self, ...)
      install_poll()
      return result
    end
  end
  if original_stop then
    base.vaicom.init.stop = function(self, ...)
      base.pcall(function() Gui.RemoveUpdateCallback(poll_menu) end)
      return original_stop(self, ...)
    end
  end

  _vaivox_report(
    "loaded {version} scanner=" .. base.tostring(original_start ~= nil) ..
    " sock=" .. base.tostring(sock ~= nil) .. " session=" .. session,
    false
  )
  publish("loaded")
end)
if not _vaivox_ok then _vaivox_report("ERROR " .. base.tostring(_vaivox_err), true) end
-- VAIVOX_F10_HOOK {version} END"""


def render_hook(port: int = DEFAULT_MENU_PORT, version: str = _HOOK_VERSION) -> str:
    """Render the Lua hook block for ``port`` (the VAIVOX menu-listener UDP port)."""
    return _HOOK_TEMPLATE.format(version=version, port=port)


class DcsHookInstaller:
    """Ensure the current VAIVOX F10 hook is present in the DCS radio command panel."""

    def __init__(self, panel_path: Path, port: int = DEFAULT_MENU_PORT) -> None:
        """Wire the panel path and the UDP port the hook should broadcast to.

        Args:
            panel_path: Path to ``RadioCommandDialogsPanel.lua`` in the DCS install.
            port: The VAIVOX menu-listener port the rendered hook sends to.
        """
        self._panel_path = panel_path
        self._port = port

    def ensure_installed(self) -> str:
        """Idempotently (re)install the current hook block; return a status reason.

        Returns:
            ``"already current"`` (no change), ``"installed"`` (added fresh),
            ``"updated"`` (replaced an older/edited block), ``"panel not found"``, or
            ``"error: ..."`` — all non-raising so a startup caller degrades cleanly.
        """
        if not self._panel_path.is_file():
            return "panel not found"
        try:
            original = self._panel_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as error:
            return f"error: {error}"

        had_block = "VAIVOX_F10_HOOK" in original
        base_content = _BLOCK_RE.sub("", original).rstrip("\n")
        desired = f"{base_content}\n\n{render_hook(self._port)}\n"
        if desired == original:
            return "already current"
        try:
            self._panel_path.write_text(desired, encoding="utf-8")
        except OSError as error:
            return f"error: {error}"
        return "updated" if had_block else "installed"


def discover_panel_path(dcs_install_dir: str | None) -> Path | None:
    """Resolve the radio command panel path under a DCS install root.

    Args:
        dcs_install_dir: The DCS World install root (e.g. the Steam ``DCSWorld`` folder), or
            ``None``.

    Returns:
        The panel path when it exists under ``dcs_install_dir``, else ``None``.
    """
    if not dcs_install_dir:
        return None
    panel = (
        Path(dcs_install_dir)
        / "Scripts"
        / "UI"
        / "RadioCommandDialogPanel"
        / "RadioCommandDialogsPanel.lua"
    )
    return panel if panel.is_file() else None


def discover_dcs_install_dir() -> str | None:
    """Best-effort discovery of the DCS World base install dir (ADR-0012).

    The radio panel is a core engine file loaded from the base install — Saved Games does
    not override it — so the hook must target the install dir. Discovery mirrors VAICOM's
    ``WinReg``: the Eagle Dynamics per-version registry key, then Steam library folders.
    Returns the first candidate whose panel file exists, or ``None`` (caller falls back to
    the ``dcs_install_dir`` setting).
    """
    for root in (*_ed_registry_roots(), *_steam_dcs_roots()):
        if discover_panel_path(root) is not None:
            return root
    return None


def _ed_registry_roots() -> list[str]:
    """Read DCS install paths from the Eagle Dynamics ``HKCU`` keys (Windows only)."""
    try:
        import winreg
    except ImportError:
        return []
    roots: list[str] = []
    for variant in ("DCS World", "DCS World OpenBeta", "DCS World Server"):
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Eagle Dynamics\{variant}"
            ) as key:
                value, _kind = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        if isinstance(value, str) and value:
            roots.append(value)
    return roots


def _steam_dcs_roots() -> list[str]:
    """Resolve candidate ``…/steamapps/common/DCSWorld`` dirs from Steam (Windows only)."""
    try:
        import winreg
    except ImportError:
        return []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam") as key:
            steam_path, _kind = winreg.QueryValueEx(key, "SteamPath")
    except OSError:
        return []
    if not isinstance(steam_path, str) or not steam_path:
        return []
    vdf = Path(steam_path) / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return _steam_dcs_roots_from_vdf(text)


#: Steam app id for DCS World (Steam edition); identifies the owning library folder.
_DCS_STEAM_APPID = "223750"


def _steam_dcs_roots_from_vdf(vdf_text: str) -> list[str]:
    """Return candidate ``…/steamapps/common/DCSWorld`` dirs from a ``libraryfolders.vdf``.

    A user may have several Steam libraries (and stale ``DCSWorld`` folders from moves), so
    the library whose ``apps`` block owns the DCS app id is yielded **first** — that is the
    install Steam actually launches. Remaining libraries follow only as a fallback.
    """
    matches = list(re.finditer(r'"path"\s+"([^"]+)"', vdf_text))
    owning: list[str] = []
    others: list[str] = []
    for index, match in enumerate(matches):
        path = match.group(1).replace("\\\\", "\\")
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(vdf_text)
        bucket = owning if _DCS_STEAM_APPID in vdf_text[match.end() : block_end] else others
        bucket.append(path)
    return [str(Path(p) / "steamapps" / "common" / "DCSWorld") for p in (*owning, *others)]


def is_dcs_running() -> bool:
    """Return whether a ``DCS.exe`` process is currently running (Windows; best effort).

    Used to decide whether a freshly (re)installed hook needs the user to **restart DCS
    now**: DCS loads the radio panel once at startup, so a running DCS holds the pre-hook
    panel — and dispatching against its stale menu can fire the wrong F10 action (ADR-0012).
    """
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq DCS.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "DCS.exe" in completed.stdout
