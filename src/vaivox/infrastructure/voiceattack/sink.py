r"""VoiceAttack command sink: send recognized text over a TCP socket.

The plugin consumes the command over a localhost TCP connection. ADR-0006 adds a
synchronous reply on this *same* connection (one ``\n``-terminated JSON line:
``{"v":1,"matched":...,"resolved_command":...}``) so reconciliation can close the loop.
This sink is **pure transport** (send bytes, read the reply, parse) — no learning logic
lives here; the parsed :class:`~vaivox.domain.telemetry.model.MatchOutcome` re-enters the
application through the :class:`~vaivox.application.ports.CommandSink` port.

Reading the reply is **best-effort** and gated by the ``await_result`` kill-switch
(``voiceattack_await_result`` in ``settings.cfg``, default ``False``): with it off the sink
is fire-and-forget (zero latency, ``return None``), exactly the legacy behaviour. With it on
(once the replying plugin is deployed, M6) the sink reads the reply until ``\n`` under a
short timeout and parses it; any failure — timeout, EOF, garbage, non-UTF-8 — degrades to
``None`` ("unknown"), never an exception and never a block of the user.
"""

from __future__ import annotations

import logging
import socket

from vaivox.application.ports import StatusLevel, StatusReporter
from vaivox.domain.telemetry.model import MatchOutcome
from vaivox.infrastructure.voiceattack import protocol

_LOGGER = logging.getLogger(__name__)

#: Default short read timeout (seconds) for the best-effort reply read (ADR-0006).
#: Kept small so a missing/slow plugin reply never adds perceptible latency to dispatch.
DEFAULT_READ_TIMEOUT = 0.3

#: Read chunk size for accumulating the ``\n``-terminated reply line.
_RECV_CHUNK = 1024


def _read_reply(sock: socket.socket, timeout: float) -> bytes:
    r"""Read the reply line from ``sock`` best-effort, accumulating until ``\n`` or EOF.

    Frames the reply per the wire protocol: the plugin's reply is one ``\n``-terminated
    line, but TCP may split or coalesce it, so this loops over :meth:`socket.socket.recv`
    rather than assuming a single read holds the whole line. The accumulated buffer
    (with or without the trailing newline) is handed to
    :func:`~vaivox.infrastructure.voiceattack.protocol.parse_match_outcome`, which
    tolerates a missing newline and surrounding whitespace.

    Best-effort: a read timeout or a peer that closes without sending (EOF, ``recv``
    returning ``b""``) simply ends the loop and returns whatever was accumulated so far
    (possibly empty). The parser maps empty/partial/garbage bytes to ``None`` ("unknown"),
    so the caller never has to distinguish those cases here.

    Args:
        sock: The connected socket the command was just sent on (read on the same
            connection). Its read timeout is set to ``timeout`` here.
        timeout: The short read timeout in seconds applied to each ``recv``.

    Returns:
        The bytes read up to and including the first ``\n`` (or all bytes received before
        EOF/timeout). Empty when the peer sent nothing before closing or timing out.
    """
    sock.settimeout(timeout)
    buffer = bytearray()
    while True:
        try:
            chunk = sock.recv(_RECV_CHUNK)
        except (TimeoutError, OSError):
            # Timeout or a low-level read error mid-reply: stop and parse what we have
            # (best-effort). A partial/empty buffer parses to None ("unknown").
            break
        if not chunk:
            # EOF: the plugin closed the connection without (finishing) a reply.
            break
        buffer.extend(chunk)
        if b"\n" in chunk:
            break
    return bytes(buffer)


class VoiceAttackCommandSink:
    """Send recognized commands to the VoiceAttack plugin over TCP."""

    def __init__(
        self,
        host: str,
        port: int,
        reporter: StatusReporter,
        *,
        await_result: bool = False,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
    ) -> None:
        """Configure the VoiceAttack endpoint and the best-effort reply read.

        Args:
            host: The VoiceAttack plugin host (usually localhost).
            port: The VoiceAttack plugin port.
            reporter: The user-facing status reporter port.
            await_result: The ``voiceattack_await_result`` kill-switch (ADR-0006). When
                ``False`` (the default) the sink is fire-and-forget — it never reads the
                reply and always returns ``None`` (zero added latency, legacy behaviour).
                When ``True`` it reads the plugin's reply best-effort and returns the parsed
                :class:`MatchOutcome`; flipped on once the replying plugin is deployed (M6).
            read_timeout: The short read timeout (seconds) for the reply, applied only when
                ``await_result`` is ``True``.
        """
        self._host = host
        self._port = port
        self._reporter = reporter
        self._await_result = await_result
        self._read_timeout = read_timeout

    def send(self, command: str) -> MatchOutcome | None:
        r"""Send ``command`` to VoiceAttack, reporting success or failure to the user.

        When ``await_result`` is enabled, reads the plugin's reply on the *same* socket
        (best-effort, framed to ``\\n``, short timeout) and parses it into a
        :class:`MatchOutcome`. Every degraded reply path — read timeout, the peer closing
        without a reply (EOF), unreadable/garbled bytes — yields ``None`` ("unknown") via
        :func:`~vaivox.infrastructure.voiceattack.protocol.parse_match_outcome`, which
        never raises. A genuine network failure (connection refused, reset) is logged and
        reported and also yields ``None``; the error is never propagated to the caller and
        the user is never blocked.

        Args:
            command: The recognized command text to dispatch, sent UTF-8 encoded.

        Returns:
            The parsed :class:`MatchOutcome` when ``await_result`` is enabled and the
            plugin sent a well-formed reply; otherwise ``None`` ("unknown") — including
            always when ``await_result`` is disabled (fire-and-forget) and on any error.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                client_socket.connect((self._host, self._port))
                client_socket.sendall(command.encode())
                reply = b""
                if self._await_result:
                    # Best-effort read of the plugin's reply on this same connection,
                    # before the `with` closes the socket.
                    reply = _read_reply(client_socket, self._read_timeout)
            _LOGGER.info("Sent text to VoiceAttack: %s", command)
            self._reporter.report(f"Sent text to VoiceAttack: {command}", StatusLevel.SUCCESS)
        except Exception as error:
            _LOGGER.error("Error calling VoiceAttack (%s:%s): %s", self._host, self._port, error)
            self._reporter.report(f"Error calling VoiceAttack: {error}", StatusLevel.ERROR)
            return None
        return protocol.parse_match_outcome(reply)
