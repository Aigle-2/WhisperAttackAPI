"""Unit tests for the VoiceAttack command sink return channel (ADR-0006).

The sink is **pure transport**: it opens the socket, sends the command, reads the plugin's
reply (when ``await_result`` is on), and **surfaces the outcome to the user**. Parsing is
delegated to :func:`~vaivox.infrastructure.voiceattack.protocol.parse_match_outcome` (the
single source of truth, exercised against the golden vectors in
``tests/unit/test_match_protocol.py``), so these tests focus on the adapter end to end over a
real one-shot localhost TCP server plus the **v1 UI surfacing** the merged sink must keep:
"VoiceAttack matched: …", "VoiceAttack has no command for: …", and the legacy
"Sent text to VoiceAttack: …".

The decisive property is **backward compatibility**: anything but a well-formed reply
(EOF, garbage, timeout, fire-and-forget) degrades to ``None`` (unknown) without raising, so
an un-rebuilt plugin behaves exactly as before.
"""

from __future__ import annotations

import socket
import threading

from vaivox.application.ports import StatusLevel
from vaivox.domain.telemetry.model import MatchOutcome
from vaivox.infrastructure.voiceattack import protocol
from vaivox.infrastructure.voiceattack.sink import VoiceAttackCommandSink


class FakeReporter:
    def __init__(self):
        self.lines = []

    def report(self, message, level=StatusLevel.INFO):
        self.lines.append((message, level))

    def levels(self):
        return [level for _message, level in self.lines]

    def messages(self):
        return [message for message, _level in self.lines]


class _OneShotServer:
    """Accept one connection, capture the command, then respond via ``handler``.

    Runs the accept loop on a daemon thread so the sink under test drives the client side
    synchronously. ``handler(conn, received_bytes)`` decides the reply (or lack of one).
    """

    def __init__(self, handler):
        self._handler = handler
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.host, self.port = self._sock.getsockname()
        self.received = None
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        try:
            conn, _ = self._sock.accept()
            with conn:
                self.received = conn.recv(4096)
                self._handler(conn, self.received)
        except OSError:
            pass

    def close(self):
        self._sock.close()
        self._thread.join(timeout=2)


# -- adapter over a real socket ------------------------------------------------------


def test_send_returns_parsed_outcome_and_reports_success():
    # The fake plugin emits the contract bytes via build_reply so it matches the parser.
    def handler(conn, _received):
        conn.sendall(protocol.build_reply(True, "go"))

    server = _OneShotServer(handler)
    reporter = FakeReporter()
    sink = VoiceAttackCommandSink(server.host, server.port, reporter)
    try:
        outcome = sink.send("go")
    finally:
        server.close()

    assert outcome == MatchOutcome(matched=True, resolved_command="go")
    assert server.received == b"go"  # the command actually reached the plugin
    assert StatusLevel.SUCCESS in reporter.levels()  # existing status reporting preserved


def test_send_surfaces_resolved_command_when_it_differs():
    # v1 UI surfacing: "VoiceAttack matched: <spoken> → <resolved>" when the plugin
    # resolved a different command than the one we sent.
    def handler(conn, _received):
        conn.sendall(protocol.build_reply(True, "Kobuleti tower"))

    server = _OneShotServer(handler)
    reporter = FakeReporter()
    sink = VoiceAttackCommandSink(server.host, server.port, reporter)
    try:
        outcome = sink.send("kobuleti")
    finally:
        server.close()

    assert outcome == MatchOutcome(matched=True, resolved_command="Kobuleti tower")
    assert StatusLevel.SUCCESS in reporter.levels()
    assert any(
        "VoiceAttack matched: kobuleti → Kobuleti tower" in message
        for message in reporter.messages()
    )


def test_send_against_plugin_that_closes_without_replying_is_unknown():
    # A pre-return-channel plugin reads the command and closes -> EOF -> unknown (parity).
    server = _OneShotServer(lambda conn, received: None)
    reporter = FakeReporter()
    sink = VoiceAttackCommandSink(server.host, server.port, reporter)
    try:
        outcome = sink.send("go")
    finally:
        server.close()

    assert outcome is None
    assert StatusLevel.SUCCESS in reporter.levels()  # still reported as sent
    assert StatusLevel.ERROR not in reporter.levels()  # EOF is not an error
    assert any("Sent text to VoiceAttack: go" in message for message in reporter.messages())


def test_send_reports_a_warning_when_voiceattack_has_no_matching_command():
    def handler(conn, _received):
        conn.sendall(protocol.build_reply(False, None))

    server = _OneShotServer(handler)
    reporter = FakeReporter()
    sink = VoiceAttackCommandSink(server.host, server.port, reporter)
    try:
        outcome = sink.send("Action Lion")
    finally:
        server.close()

    assert outcome == MatchOutcome(matched=False, resolved_command=None)
    # The unrecognized command is surfaced (was silent before), so a wrong phrasing is obvious.
    assert StatusLevel.WARNING in reporter.levels()
    assert any(
        "VoiceAttack has no command for: Action Lion" in message for message in reporter.messages()
    )


def test_send_with_malformed_reply_is_unknown():
    server = _OneShotServer(lambda conn, received: conn.sendall(b"garbage\n"))
    reporter = FakeReporter()
    sink = VoiceAttackCommandSink(server.host, server.port, reporter)
    try:
        outcome = sink.send("go")
    finally:
        server.close()

    assert outcome is None
    assert StatusLevel.SUCCESS in reporter.levels()


def test_send_times_out_when_plugin_never_replies():
    release = threading.Event()

    def handler(conn, _received):
        release.wait(timeout=2)  # hold the connection open without replying

    server = _OneShotServer(handler)
    reporter = FakeReporter()
    sink = VoiceAttackCommandSink(server.host, server.port, reporter, read_timeout=0.05)
    try:
        outcome = sink.send("go")
        assert outcome is None
        assert StatusLevel.SUCCESS in reporter.levels()
    finally:
        release.set()
        server.close()


def test_send_fire_and_forget_does_not_read_reply_and_reports_success():
    # await_result=False: the plugin would reply "matched", but the sink must NOT read it,
    # must return None, and must still report success (legacy behaviour, zero added latency).
    def handler(conn, _received):
        conn.sendall(protocol.build_reply(True, "go"))

    server = _OneShotServer(handler)
    reporter = FakeReporter()
    sink = VoiceAttackCommandSink(server.host, server.port, reporter, await_result=False)
    try:
        outcome = sink.send("go")
    finally:
        server.close()

    assert outcome is None
    assert server.received == b"go"  # the command was still sent
    assert StatusLevel.SUCCESS in reporter.levels()
    assert StatusLevel.ERROR not in reporter.levels()


def test_send_reports_error_and_returns_none_when_unreachable():
    # Bind then immediately release the port so the connect is refused (the failure path).
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    _host, port = probe.getsockname()
    probe.close()

    reporter = FakeReporter()
    outcome = VoiceAttackCommandSink("127.0.0.1", port, reporter).send("go")

    assert outcome is None
    assert StatusLevel.ERROR in reporter.levels()
