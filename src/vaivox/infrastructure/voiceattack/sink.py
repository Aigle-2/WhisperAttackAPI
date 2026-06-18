"""VoiceAttack command sink: send recognized text over a TCP socket (ADR-0006).

The sink dispatches the reconciled command to our C# VoiceAttack plugin and then reads a
**synchronous reply on the same connection** — one JSON line
``{ "text", "matched", "resolved_command" }`` the plugin writes right after
``Command.Exists`` (before the in-game radio call finishes), so the round-trip adds
negligible latency. The reply closes the reconciliation loop: the routing use case records
the :class:`~vaivox.domain.telemetry.model.MatchOutcome` in telemetry and stamps vocabulary
usage on a match (ADR-0004).

**Backward compatibility:** a pre-return-channel plugin sends no reply and just closes the
socket. The read uses a short timeout and treats EOF / timeout / a malformed line as an
*unknown* outcome (``None``), so behaviour is unchanged against an un-rebuilt plugin — the
command still fires, telemetry records ``unknown``, and no usage is stamped.
"""

from __future__ import annotations

import json
import logging
import socket

from vaivox.application.ports import StatusLevel, StatusReporter
from vaivox.domain.telemetry.model import MatchOutcome

_LOGGER = logging.getLogger(__name__)

#: Seconds to wait for the plugin's reply before treating the outcome as unknown. Short by
#: design: the plugin replies right after the match decision, so a real reply lands almost
#: immediately and an un-rebuilt plugin (no reply) costs at most this on the Python side.
_DEFAULT_REPLY_TIMEOUT_SECONDS = 0.5

#: Read-buffer size and an overall cap for the reply (one small JSON line); the cap guards
#: against a misbehaving peer streaming unboundedly on the response socket.
_REPLY_BUFFER_BYTES = 4096
_REPLY_MAX_BYTES = 64 * 1024


class VoiceAttackCommandSink:
    """Send recognized commands to the VoiceAttack plugin over TCP and read the outcome."""

    def __init__(
        self,
        host: str,
        port: int,
        reporter: StatusReporter,
        reply_timeout: float = _DEFAULT_REPLY_TIMEOUT_SECONDS,
    ) -> None:
        """Configure the VoiceAttack endpoint.

        Args:
            host: The VoiceAttack plugin host (usually localhost).
            port: The VoiceAttack plugin port.
            reporter: The user-facing status reporter port.
            reply_timeout: Seconds to wait for the plugin's match reply before treating the
                outcome as unknown (defaults to a short, near-instant window).
        """
        self._host = host
        self._port = port
        self._reporter = reporter
        self._reply_timeout = reply_timeout

    def send(self, command: str) -> MatchOutcome | None:
        """Send ``command`` to VoiceAttack and return its match outcome (ADR-0006).

        Reports success or failure to the user exactly as before; the returned outcome is
        the plugin's reply, or ``None`` when unknown (no reply, timeout, or malformed line).

        Args:
            command: The reconciled command text to dispatch.

        Returns:
            The parsed :class:`MatchOutcome`, or ``None`` when the outcome is unknown.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                client_socket.connect((self._host, self._port))
                client_socket.sendall(command.encode())
                # ADR-0006: read the plugin's MatchOutcome reply on this same socket before
                # the `with` closes it. Self-contained error handling -> never raises here.
                outcome = self._read_match_outcome(client_socket)
            _LOGGER.info("Sent text to VoiceAttack: %s", command)
            self._reporter.report(f"Sent text to VoiceAttack: {command}", StatusLevel.SUCCESS)
            return outcome
        except Exception as error:
            _LOGGER.error("Error calling VoiceAttack (%s:%s): %s", self._host, self._port, error)
            self._reporter.report(f"Error calling VoiceAttack: {error}", StatusLevel.ERROR)
            return None

    def _read_match_outcome(self, client_socket: socket.socket) -> MatchOutcome | None:
        """Read and parse the plugin's reply, degrading to ``None`` on any shortfall.

        Args:
            client_socket: The connected socket the command was sent on.

        Returns:
            The parsed :class:`MatchOutcome`, or ``None`` for EOF (a plugin that closed
            without replying), a timeout, a socket error, or a malformed reply.
        """
        client_socket.settimeout(self._reply_timeout)
        chunks = bytearray()
        try:
            while b"\n" not in chunks and len(chunks) < _REPLY_MAX_BYTES:
                chunk = client_socket.recv(_REPLY_BUFFER_BYTES)
                if not chunk:  # EOF: a pre-return-channel plugin closed without replying.
                    break
                chunks.extend(chunk)
        except TimeoutError:
            _LOGGER.debug(
                "VoiceAttack sent no match reply within %ss; outcome unknown.",
                self._reply_timeout,
            )
            return None
        except OSError as error:
            _LOGGER.debug("Error reading VoiceAttack match reply: %s; outcome unknown.", error)
            return None
        return _parse_match_outcome(chunks)


def _parse_match_outcome(data: bytes | bytearray) -> MatchOutcome | None:
    """Parse the plugin's reply bytes into a :class:`MatchOutcome` (lenient, never raises).

    The reply is one JSON object ``{ "text", "matched", "resolved_command" }`` terminated by
    a newline; only the first line is read. Anything missing, mistyped, or unparseable yields
    ``None`` (an unknown outcome) so a malformed plugin can never crash the routing flow.

    Args:
        data: The raw bytes read from the reply socket (may be empty).

    Returns:
        The parsed outcome, or ``None`` when the reply is absent or malformed.
    """
    line = bytes(data).split(b"\n", 1)[0].strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        _LOGGER.warning("Malformed VoiceAttack match reply: %r", line[:200])
        return None
    if not isinstance(record, dict):
        return None
    matched = record.get("matched")
    if not isinstance(matched, bool):
        return None
    resolved = record.get("resolved_command")
    resolved_command = resolved if isinstance(resolved, str) else None
    return MatchOutcome(matched=matched, resolved_command=resolved_command)
