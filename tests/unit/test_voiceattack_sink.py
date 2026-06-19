"""Unit tests for the VoiceAttack command sink return channel (ADR-0006).

Two layers: the pure reply parser (``_parse_match_outcome``) over crafted bytes, and the
adapter end to end against a real one-shot localhost TCP server that replies, closes early
(a pre-return-channel plugin), replies garbage, or stalls. The decisive property is
**backward compatibility**: anything but a well-formed reply degrades to ``None`` (unknown)
without raising, so an un-rebuilt plugin behaves exactly as before.
"""

from __future__ import annotations

import socket
import threading

from vaivox.application.ports import StatusLevel
from vaivox.domain.telemetry.model import MatchOutcome
from vaivox.infrastructure.voiceattack.sink import VoiceAttackCommandSink, _parse_match_outcome


class FakeReporter:
    def __init__(self):
        self.lines = []

    def report(self, message, level=StatusLevel.INFO):
        self.lines.append((message, level))

    def levels(self):
        return [level for _message, level in self.lines]


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


# -- pure parser ---------------------------------------------------------------------


def test_parse_valid_matched_reply():
    line = b'{"text": "Kobuleti tower", "matched": true, "resolved_command": "Kobuleti tower"}\n'

    assert _parse_match_outcome(line) == MatchOutcome(
        matched=True, resolved_command="Kobuleti tower"
    )


def test_parse_valid_not_matched_reply():
    reply = b'{"text": "nope", "matched": false, "resolved_command": null}'

    assert _parse_match_outcome(reply) == MatchOutcome(matched=False, resolved_command=None)


def test_parse_reads_only_the_first_line():
    # Only the first newline-terminated record is consumed; trailing bytes are ignored.
    line = b'{"matched": true, "resolved_command": "go"}\ntrailing garbage'

    assert _parse_match_outcome(line) == MatchOutcome(matched=True, resolved_command="go")


def test_parse_empty_is_unknown():
    assert _parse_match_outcome(b"") is None
    assert _parse_match_outcome(b"   \n") is None


def test_parse_malformed_json_is_unknown():
    assert _parse_match_outcome(b"not json at all\n") is None


def test_parse_non_object_is_unknown():
    assert _parse_match_outcome(b"[1, 2, 3]\n") is None


def test_parse_missing_or_mistyped_matched_is_unknown():
    assert _parse_match_outcome(b'{"resolved_command": "go"}') is None
    assert _parse_match_outcome(b'{"matched": "true"}') is None  # string, not bool


def test_parse_non_string_resolved_command_falls_back_to_none():
    assert _parse_match_outcome(b'{"matched": true, "resolved_command": 7}') == MatchOutcome(
        matched=True, resolved_command=None
    )


# -- adapter over a real socket ------------------------------------------------------


def test_send_returns_parsed_outcome_and_reports_success():
    def handler(conn, _received):
        conn.sendall(b'{"text":"go","matched":true,"resolved_command":"go"}\n')

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


def test_send_reports_a_warning_when_voiceattack_has_no_matching_command():
    def handler(conn, _received):
        conn.sendall(b'{"text":"Action Lion","matched":false,"resolved_command":null}\n')

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
    sink = VoiceAttackCommandSink(server.host, server.port, reporter, reply_timeout=0.05)
    try:
        outcome = sink.send("go")
        assert outcome is None
        assert StatusLevel.SUCCESS in reporter.levels()
    finally:
        release.set()
        server.close()


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
