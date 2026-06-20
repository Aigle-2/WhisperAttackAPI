"""VAICOM F10 action sink: fire a live DCS F10 menu item via ``doAction`` (ADR-0012).

Mission F10 items imported by VAICOM are **not** VoiceAttack commands, so they cannot be
dispatched through :class:`~vaivox.infrastructure.voiceattack.sink.VoiceAttackCommandSink`.
VAICOM fires them by sending DCS a UDP datagram that DCS turns into a
``missionCommands.doAction`` call. This adapter replicates exactly that datagram.

The contract was reverse-engineered from VAICOM-Community source and confirmed live; see
:doc:`/VAICOM_F10_EXECUTION_CONTRACT`. In short:

- VAICOM (``ConstructMessage.cs`` -> ``SetMenuItemAction.cs``) appends the menu item's
  ``actionIndex`` to ``actionsequence`` and sends
  ``{"type": "mission.player.actionsequence", "actionsequence": [<actionIndex>]}`` to its
  client send port ``127.0.0.1:33491``.
- DCS (``Append.Core.RadioCommandDialogsPanel.lua``) loops the array and calls
  ``missionCommands.doAction(actionsequence[i])``. ``doAction`` fires a registered mission
  action by its handle, so **one** ``actionIndex`` fires any item — submenu nesting is
  irrelevant; it is not a navigation path.

**Fire-and-forget:** DCS sends no acknowledgement on this path, so the sink returns a
:class:`~vaivox.domain.commands.model.DispatchOutcome` describing what it sent. ``accepted``
means the datagram was sent (or could not be), not that DCS executed it. There is no
:class:`~vaivox.domain.telemetry.model.MatchOutcome` for F10 dispatch.
"""

from __future__ import annotations

import json
import logging
import socket
from collections.abc import Callable, Mapping

from vaivox.application.ports import StatusLevel, StatusReporter
from vaivox.domain.commands.model import DispatchOutcome, DispatchTargetKind, VaicomF10Action

_LOGGER = logging.getLogger(__name__)

#: VAICOM's ``ActionIndexSequence`` message type string (``Static.cs`` in VAICOM-Community).
_ACTION_SEQUENCE_TYPE = "mission.player.actionsequence"

#: VAICOM's client send port: the export relay forwards :33491 to the in-sim panel receiver
#: bound at :33334 (``UDP.cs`` ``ClientSendPort``). Sending here mirrors VAICOM exactly.
DEFAULT_VAICOM_F10_HOST = "127.0.0.1"
DEFAULT_VAICOM_F10_PORT = 33491


class UdpVaicomF10ActionSink:
    """Fire a live VAICOM F10 action by sending DCS the ``doAction`` datagram over UDP."""

    def __init__(
        self,
        host: str = DEFAULT_VAICOM_F10_HOST,
        port: int = DEFAULT_VAICOM_F10_PORT,
        reporter: StatusReporter | None = None,
        live_index: Callable[[], Mapping[str, int]] | None = None,
    ) -> None:
        """Configure the DCS/VAICOM action endpoint.

        Args:
            host: The host VAICOM's command relay listens on (loopback).
            port: The UDP port VAICOM's client sends actions to (default ``33491``).
            reporter: Optional user-facing status reporter.
            live_index: Current-session label-to-index provider. It is consulted at send
                time so a surface resolved before a menu rebuild cannot dispatch a stale
                handle.
        """
        self._host = host
        self._port = port
        self._reporter = reporter
        self._live_index = live_index

    def dispatch(self, action: VaicomF10Action) -> DispatchOutcome:
        """Resolve ``action`` from the live map and send its current index to DCS.

        Args:
            action: The resolved live F10 action to fire.

        Returns:
            A :class:`DispatchOutcome`; ``accepted`` is ``True`` when the datagram was sent,
            ``False`` when there is no live ``ActionIndex`` to send or the socket errored.
        """
        action_index = self._current_action_index(action.label)
        if action_index is None:
            return self._reject(
                action,
                "no current live ActionIndex available; wait up to 6 seconds for the DCS "
                "menu heartbeat, then restart DCS if the handshake is still missing",
            )

        payload = {"type": _ACTION_SEQUENCE_TYPE, "actionsequence": [action_index]}
        try:
            datagram = json.dumps(payload).encode("utf-8")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
                udp_socket.sendto(datagram, (self._host, self._port))
        except OSError as error:
            _LOGGER.error(
                "Error sending VAICOM F10 action to %s:%s: %s", self._host, self._port, error
            )
            self._report(f"Error firing F10 '{action.label}': {error}", StatusLevel.ERROR)
            return self._outcome(action, accepted=False, detail=f"UDP send failed: {error}")

        _LOGGER.info(
            "Fired VAICOM F10 action '%s' (actionIndex %s) to %s:%s",
            action.label,
            action_index,
            self._host,
            self._port,
        )
        self._report(f"F10 action fired: {action.label}", StatusLevel.SUCCESS)
        return self._outcome(
            action,
            accepted=True,
            detail=f"DCS doAction actionIndex {action_index} via {_ACTION_SEQUENCE_TYPE}",
        )

    def _current_action_index(self, label: str) -> int | None:
        """Resolve ``label`` from the authoritative map at the instant of dispatch."""
        if self._live_index is None:
            return None
        try:
            live = self._live_index()
        except Exception as error:
            _LOGGER.warning("Cannot read the live F10 index: %s", error)
            return None
        folded = label.casefold()
        index = next((value for name, value in live.items() if name.casefold() == folded), None)
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            return None
        return index

    def _reject(self, action: VaicomF10Action, reason: str) -> DispatchOutcome:
        """Report and return a non-accepted outcome for an unsendable action."""
        _LOGGER.warning("Cannot fire VAICOM F10 action '%s': %s", action.label, reason)
        self._report(f"Cannot fire F10 '{action.label}': {reason}", StatusLevel.WARNING)
        return self._outcome(action, accepted=False, detail=reason)

    @staticmethod
    def _outcome(action: VaicomF10Action, *, accepted: bool, detail: str) -> DispatchOutcome:
        """Build the typed dispatch outcome recorded in telemetry."""
        return DispatchOutcome(
            target_kind=DispatchTargetKind.VAICOM_F10_ACTION.value,
            accepted=accepted,
            resolved_target=action.identifier,
            detail=detail,
        )

    def _report(self, message: str, level: StatusLevel) -> None:
        """Forward a status line to the reporter when one is wired."""
        if self._reporter is not None:
            self._reporter.report(message, level)
