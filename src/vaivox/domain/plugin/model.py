"""Plugin runtime-health value objects (setup diagnostics; ADR-0006 handshake).

The VoiceAttack plugin announces itself to the app over the control socket when it
loads (a ``hello`` handshake). These pure value objects capture what it reported and
whether it is compatible with this app build, so the setup/health surface can tell
the user — without guessing — that the plugin is connected and speaking a protocol
this app understands.

Compatibility is judged on the **return-channel wire protocol version**
(``MATCH_PROTOCOL_VERSION``), never the plugin's assembly/build string: the plugin
and the app carry independent release lines (the plugin ships ``1.0.0.0`` while the
app is on its own SemVer), so comparing the two would nag on every harmless bump.
Only a protocol drift is a genuine incompatibility that requires reinstalling the
plugin DLL. The build version is carried for **display only**.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class PluginHandshake:
    """What the VoiceAttack plugin reported about itself at connect time.

    Attributes:
        plugin_version: The plugin assembly/build version string, e.g. ``"1.0.0.0"``.
            Informational display only — a separate release line from the app version,
            never used to judge compatibility.
        protocol_version: The return-channel wire-protocol version the plugin emits,
            mirrored from the plugin's ``MatchProtocolVersion``. This is the sole axis
            compatibility is judged on.
    """

    plugin_version: str
    protocol_version: int


class PluginCompatibility(StrEnum):
    """Whether the connected plugin is compatible with this app build."""

    UP_TO_DATE = "up_to_date"
    PROTOCOL_MISMATCH = "protocol_mismatch"
    UNKNOWN = "unknown"


def evaluate_compatibility(
    handshake: PluginHandshake | None, app_protocol_version: int
) -> PluginCompatibility:
    """Judge the connected plugin against this app's return-channel protocol.

    The plugin build version is deliberately ignored here (see the module docstring):
    only the wire-protocol version decides compatibility.

    Args:
        handshake: What the plugin announced at connect time, or ``None`` when no
            handshake has been received yet — the plugin is not loaded, has not
            connected, or is an older build that predates the handshake.
        app_protocol_version: This app's return-channel protocol version
            (``MATCH_PROTOCOL_VERSION``), passed in so the domain stays free of the
            infrastructure transport module.

    Returns:
        :attr:`PluginCompatibility.UNKNOWN` when nothing has been reported yet,
        :attr:`PluginCompatibility.UP_TO_DATE` when the plugin speaks this app's
        protocol version, or :attr:`PluginCompatibility.PROTOCOL_MISMATCH` when the
        versions differ (the plugin DLL should be reinstalled).
    """
    if handshake is None:
        return PluginCompatibility.UNKNOWN
    if handshake.protocol_version == app_protocol_version:
        return PluginCompatibility.UP_TO_DATE
    return PluginCompatibility.PROTOCOL_MISMATCH
