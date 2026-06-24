r"""VoiceAttack command sink: send recognized text over a TCP socket (ADR-0006).

The sink dispatches the reconciled command to our C# VoiceAttack plugin and then reads a
**synchronous reply on the same connection** — one JSON line
``{"v":1,"matched":...,"resolved_command":...}`` the plugin writes right after
``Command.Exists`` (before the in-game radio call finishes), so the round-trip adds
negligible latency. The reply closes the reconciliation loop: the routing use case records
the :class:`~vaivox.domain.telemetry.model.MatchOutcome` in telemetry and stamps vocabulary
usage on a match (ADR-0004). The reply is framed and parsed by the single source of truth,
:func:`~vaivox.infrastructure.voiceattack.protocol.parse_match_outcome`; this module is pure
transport (open the socket, send, read, surface the outcome) — no parsing or learning logic.

**``await_result`` kill-switch:** reading the reply is gated by ``await_result``
(``voiceattack_await_result`` in ``settings.cfg``). With it **on** (the default on this
branch) the sink reads the reply best-effort under a short ``read_timeout`` and returns the
parsed outcome; any shortfall — timeout, EOF, garbage, non-UTF-8 — degrades to ``None``
("unknown"), never an exception. With it **off** the sink is fire-and-forget: it never reads
the reply and always returns ``None`` (zero added latency), exactly the legacy behaviour.

**Backward compatibility:** a pre-return-channel plugin sends no reply and just closes the
socket. With ``await_result`` on, the read uses a short timeout and treats EOF / timeout / a
malformed line as an *unknown* outcome (``None``), so behaviour is unchanged against an
un-rebuilt plugin — the command still fires, telemetry records ``unknown``, and no usage is
stamped.
"""

from __future__ import annotations

import logging
import socket

from vaivox.application.ports import StatusLevel, StatusReporter
from vaivox.domain.telemetry.model import MatchOutcome
from vaivox.infrastructure.voiceattack import protocol

_LOGGER = logging.getLogger(__name__)

#: Default short read timeout (seconds) for the best-effort reply read (ADR-0006). Short by
#: design: the plugin replies right after the match decision, so a real reply lands almost
#: immediately and a missing/slow reply never adds perceptible latency to dispatch.
_DEFAULT_READ_TIMEOUT_SECONDS = 0.5

#: Read chunk size and an overall cap for the reply (one small JSON line); the cap guards
#: against a misbehaving peer streaming unboundedly on the response socket.
_RECV_CHUNK_BYTES = 4096
_REPLY_MAX_BYTES = 64 * 1024


class VoiceAttackCommandSink:
    """Send recognized commands to the VoiceAttack plugin over TCP and read the outcome."""

    def __init__(
        self,
        host: str,
        port: int,
        reporter: StatusReporter,
        *,
        await_result: bool = True,
        read_timeout: float = _DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> None:
        """Configure the VoiceAttack endpoint and the best-effort reply read.

        Args:
            host: The VoiceAttack plugin host (usually localhost).
            port: The VoiceAttack plugin port.
            reporter: The user-facing status reporter port.
            await_result: The ``voiceattack_await_result`` kill-switch (ADR-0006). When
                ``True`` (the default on this branch) the sink reads the plugin's reply
                best-effort and returns the parsed :class:`MatchOutcome`. When ``False`` it
                is fire-and-forget — it never reads the reply and always returns ``None``
                (zero added latency, legacy behaviour).
            read_timeout: The short read timeout (seconds) for the reply, applied only when
                ``await_result`` is ``True``.
        """
        self._host = host
        self._port = port
        self._reporter = reporter
        self._await_result = await_result
        self._read_timeout = read_timeout

    def send(self, command: str) -> MatchOutcome | None:
        r"""Send ``command`` to VoiceAttack and return its match outcome (ADR-0006).

        Reports success or failure to the user; surfaces whether VoiceAttack actually had a
        command for the text (the plugin return channel) so a wrong phrasing is obvious
        rather than silent. The returned outcome is the plugin's reply, or ``None`` when
        unknown (fire-and-forget, no reply, timeout, EOF, or a malformed line). Every
        degraded reply path degrades to ``None`` via
        :func:`~vaivox.infrastructure.voiceattack.protocol.parse_match_outcome`, which never
        raises; a genuine network failure (connection refused, reset) is logged, reported,
        and also yields ``None`` — the error is never propagated and the user is never
        blocked.

        Args:
            command: The reconciled command text to dispatch, sent UTF-8 encoded.

        Returns:
            The parsed :class:`MatchOutcome` when ``await_result`` is enabled and the plugin
            sent a well-formed reply; otherwise ``None`` ("unknown") — including always when
            ``await_result`` is disabled (fire-and-forget) and on any error.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                client_socket.connect((self._host, self._port))
                client_socket.sendall(command.encode())
                reply = b""
                if self._await_result:
                    # ADR-0006: best-effort read of the plugin's reply on this same socket,
                    # before the `with` closes it. Self-contained -> never raises here.
                    reply = self._read_reply(client_socket)
            _LOGGER.info("Sent text to VoiceAttack: %s", command)
            outcome = protocol.parse_match_outcome(reply)
            self._report_outcome(command, outcome)
            return outcome
        except Exception as error:
            _LOGGER.error("Error calling VoiceAttack (%s:%s): %s", self._host, self._port, error)
            self._reporter.report(f"Error calling VoiceAttack: {error}", StatusLevel.ERROR)
            return None

    def _report_outcome(self, command: str, outcome: MatchOutcome | None) -> None:
        """Report what was sent and whether VoiceAttack actually had a command for it.

        ``matched`` comes from the plugin return channel (ADR-0006). Surfacing it makes an
        unrecognized command (e.g. a wrong F10 phrasing) obvious instead of silent — the
        rebuilt plugin replies, while an un-rebuilt one (or fire-and-forget) yields ``None``
        and the original "Sent text" message, preserving parity.
        """
        if outcome is None:
            self._reporter.report(f"Sent text to VoiceAttack: {command}", StatusLevel.SUCCESS)
        elif not outcome.matched:
            self._reporter.report(f"VoiceAttack has no command for: {command}", StatusLevel.WARNING)
        elif outcome.resolved_command and outcome.resolved_command != command:
            self._reporter.report(
                f"VoiceAttack matched: {command} → {outcome.resolved_command}",
                StatusLevel.SUCCESS,
            )
        else:
            self._reporter.report(f"VoiceAttack matched: {command}", StatusLevel.SUCCESS)

    def _read_reply(self, client_socket: socket.socket) -> bytes:
        r"""Read the plugin's reply line best-effort, accumulating until ``\n`` or EOF.

        Frames the reply per the wire protocol: the plugin's reply is one ``\n``-terminated
        line, but TCP may split or coalesce it, so this loops over :meth:`socket.socket.recv`
        rather than assuming a single read holds the whole line. The accumulated buffer (with
        or without the trailing newline) is handed to
        :func:`~vaivox.infrastructure.voiceattack.protocol.parse_match_outcome`, which
        tolerates a missing newline and surrounding whitespace.

        Best-effort: a read timeout or a peer that closes without sending (EOF, ``recv``
        returning ``b""``) simply ends the loop and returns whatever was accumulated so far
        (possibly empty). The parser maps empty/partial/garbage bytes to ``None``
        ("unknown"), so the caller never has to distinguish those cases here.

        Args:
            client_socket: The connected socket the command was just sent on (read on the
                same connection). Its read timeout is set to ``read_timeout`` here.

        Returns:
            The bytes read up to and including the first ``\n`` (or all bytes received before
            EOF/timeout). Empty when the peer sent nothing before closing or timing out.
        """
        client_socket.settimeout(self._read_timeout)
        buffer = bytearray()
        while b"\n" not in buffer and len(buffer) < _REPLY_MAX_BYTES:
            try:
                chunk = client_socket.recv(_RECV_CHUNK_BYTES)
            except TimeoutError:
                _LOGGER.debug(
                    "VoiceAttack sent no match reply within %ss; outcome unknown.",
                    self._read_timeout,
                )
                break
            except OSError as error:
                _LOGGER.debug("Error reading VoiceAttack match reply: %s; outcome unknown.", error)
                break
            if not chunk:  # EOF: a pre-return-channel plugin closed without replying.
                break
            buffer.extend(chunk)
        # Frame to the first line: a single ``recv`` can deliver the reply line AND trailing
        # bytes together, so hand the parser only the first ``\n``-terminated line — trailing
        # data never degrades a valid reply to ``None`` (matches v1's first-line semantics).
        framed = bytes(buffer)
        newline_index = framed.find(b"\n")
        return framed if newline_index == -1 else framed[: newline_index + 1]
