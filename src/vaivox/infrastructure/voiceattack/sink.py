"""VoiceAttack command sink: send recognized text over a TCP socket.

The plugin currently consumes the command fire-and-forget. ADR-0006 adds a
synchronous reply on this *same* connection (``{ text, matched, resolved_command }``)
so reconciliation can close the loop; the seam for reading that reply is marked below
and the :class:`~vaivox.domain.telemetry.model.MatchOutcome` VO already exists. Until
the plugin is rebuilt (Phase 5) the sink stays fire-and-forget for behaviour parity.
"""

from __future__ import annotations

import logging
import socket

from vaivox.application.ports import StatusLevel, StatusReporter

_LOGGER = logging.getLogger(__name__)


class VoiceAttackCommandSink:
    """Send recognized commands to the VoiceAttack plugin over TCP."""

    def __init__(self, host: str, port: int, reporter: StatusReporter) -> None:
        """Configure the VoiceAttack endpoint.

        Args:
            host: The VoiceAttack plugin host (usually localhost).
            port: The VoiceAttack plugin port.
            reporter: The user-facing status reporter port.
        """
        self._host = host
        self._port = port
        self._reporter = reporter

    def send(self, command: str) -> None:
        """Send ``command`` to VoiceAttack, reporting success or failure to the user."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                client_socket.connect((self._host, self._port))
                client_socket.sendall(command.encode())
                # Phase 5 (ADR-0006): read MatchOutcome on this same socket here,
                # before the `with` closes it, then hand it to the TelemetrySink.
            _LOGGER.info("Sent text to VoiceAttack: %s", command)
            self._reporter.report(f"Sent text to VoiceAttack: {command}", StatusLevel.SUCCESS)
        except Exception as error:
            _LOGGER.error("Error calling VoiceAttack (%s:%s): %s", self._host, self._port, error)
            self._reporter.report(f"Error calling VoiceAttack: {error}", StatusLevel.ERROR)
