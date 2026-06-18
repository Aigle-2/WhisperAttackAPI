"""Centralized product identity (ADR-0002, ADR-0003).

Every externally observable identity value — the product name, the VoiceAttack plugin
GUID, the per-user data directory, the log file, the single-instance key, the TCP
ports, and the window/tray titles — lives here so VAIVOX never clobbers an upstream
WhisperAttack install and so a rebrand is a one-file change. The composition root and
``main`` resolve everything through the :data:`VAIVOX` instance.
"""

from __future__ import annotations

from dataclasses import dataclass

from vaivox import __version__


@dataclass(frozen=True)
class ProductIdentity:
    """The product's external identity surface.

    Attributes:
        name: Display name (window/tray title, log lines).
        version: Application version string.
        plugin_guid: The VoiceAttack plugin GUID (must differ from upstream).
        data_dir_name: Folder name under ``%LOCALAPPDATA%`` for config and logs.
        log_file_name: Log file name within the data directory.
        instance_lock_name: Single-instance lock file name within the data directory.
        control_host: Host the inbound control socket binds to.
        control_port: Port the inbound control socket binds to (plugin -> app).
        voiceattack_host: Host of the VoiceAttack plugin's listener (app -> plugin).
        voiceattack_port: Port of the VoiceAttack plugin's listener.
        api_host: Host the introspection API binds to (localhost).
        api_port: Default introspection API port (off by default; see ADR-0010).
    """

    name: str
    version: str
    plugin_guid: str
    data_dir_name: str
    log_file_name: str
    instance_lock_name: str
    control_host: str
    control_port: int
    voiceattack_host: str
    voiceattack_port: int
    api_host: str
    api_port: int

    @property
    def window_title(self) -> str:
        """The window/tray title."""
        return self.name


#: The canonical VAIVOX identity. Ports keep their historical defaults (ADR-0002:
#: VAIVOX and upstream never run two STT servers at once), but every reference now
#: resolves through this single object rather than a scattered literal.
VAIVOX = ProductIdentity(
    name="VAIVOX",
    version=__version__,
    plugin_guid="{ED0BA443-726F-4A9F-AF05-DB400F39A501}",
    data_dir_name="VAIVOX",
    log_file_name="VAIVOX.log",
    instance_lock_name="vaivox",
    control_host="127.0.0.1",
    control_port=65432,
    voiceattack_host="127.0.0.1",
    voiceattack_port=65433,
    api_host="127.0.0.1",
    api_port=8765,
)
