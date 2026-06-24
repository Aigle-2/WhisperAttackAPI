r"""The VoiceAttack sink round-trips against a fake-plugin TCP server (ADR-0006).

Layer-3 *plumbing* tests: the **real** :class:`VoiceAttackCommandSink` talks to a small
fake-plugin TCP server on an ephemeral localhost port. They prove the socket client — the
framing (read until ``\n``), the short read timeout, the best-effort fallback to ``None`` on
every degraded path, the ``await_result`` fire-and-forget kill-switch, and the v1 UI
surfacing of the match — independently of the wire-protocol parser and the learning logic
(a full layer above). No microphone, no VoiceAttack, no Windows.

The fake plugin's "matched" / "not-found" replies are produced by
:func:`~vaivox.infrastructure.voiceattack.protocol.build_reply`, the same serializer the
real plugin must reproduce byte-for-byte, so the fixture emits exactly the contract bytes the
parser consumes rather than hand-rolled JSON.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager, suppress
from typing import Any

import pytest

from vaivox.application.ports import StatusLevel
from vaivox.domain.telemetry.model import MatchOutcome
from vaivox.infrastructure.voiceattack import protocol
from vaivox.infrastructure.voiceattack.sink import VoiceAttackCommandSink

_HOST = "127.0.0.1"

# build_reply is the single source of truth for the reply bytes; the fake plugin emits via it
# so the fixture stays aligned with the frozen contract (and the C# plugin tested against it).
_MATCHED_REPLY = protocol.build_reply(True, "Tower, request taxi")
_NOT_FOUND_REPLY = protocol.build_reply(False, None)


class FakeReporter:
    """A StatusReporter fake recording every (message, level) reported."""

    def __init__(self) -> None:
        self.reports: list[tuple[str, StatusLevel]] = []

    def report(self, message: str, level: StatusLevel = StatusLevel.INFO) -> None:
        self.reports.append((message, level))

    def errors(self) -> list[str]:
        return [msg for msg, level in self.reports if level is StatusLevel.ERROR]

    def messages(self) -> list[str]:
        return [msg for msg, _level in self.reports]


class FakePluginServer:
    """A tiny configurable fake-plugin TCP server on an ephemeral localhost port.

    Accepts one connection at a time on a daemon thread, reads the request, then behaves per
    the injected ``responder``: replying with bytes, replying slowly, sending garbage, or
    closing without a reply (EOF). It records each received request so a test can assert the
    fire-and-forget path never triggered a read on the sink side.
    """

    def __init__(self, responder: Callable[[socket.socket], None]) -> None:
        self._responder = responder
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((_HOST, 0))
        self._server.listen()
        self._server.settimeout(1.0)
        self.port: int = self._server.getsockname()[1]
        self.requests: list[bytes] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except (TimeoutError, OSError):
                continue
            with conn:
                try:
                    request = conn.recv(4096)
                    self.requests.append(request)
                    self._responder(conn)
                except OSError:
                    # The client may have closed early (fire-and-forget); not an error here.
                    pass

    def close(self) -> None:
        self._stop.set()
        self._server.close()
        self._thread.join(timeout=2.0)


def _make_sink(port: int, reporter: FakeReporter, **kwargs: Any) -> VoiceAttackCommandSink:
    """Build the real sink pointed at the fake plugin's port (await_result on by default)."""
    kwargs.setdefault("await_result", True)
    kwargs.setdefault("read_timeout", 0.3)
    return VoiceAttackCommandSink(_HOST, port, reporter, **kwargs)


@pytest.fixture
def reporter() -> FakeReporter:
    return FakeReporter()


@contextmanager
def _server(responder: Callable[[socket.socket], None]) -> Iterator[FakePluginServer]:
    """Run a fake-plugin server for the duration of the ``with`` block, then close it."""
    plugin = FakePluginServer(responder)
    try:
        yield plugin
    finally:
        plugin.close()


# -- responders --------------------------------------------------------------------------


def _reply_with(payload: bytes) -> Callable[[socket.socket], None]:
    def responder(conn: socket.socket) -> None:
        conn.sendall(payload)

    return responder


def _reply_slowly(payload: bytes, delay: float) -> Callable[[socket.socket], None]:
    def responder(conn: socket.socket) -> None:
        time.sleep(delay)
        with suppress(OSError):
            conn.sendall(payload)  # the client likely timed out and closed; harmless

    return responder


def _close_without_reply(conn: socket.socket) -> None:
    """Accept and read the request, then return — closing the connection (EOF), no reply."""
    return None


# -- matched / not-found (build_reply contract bytes) ------------------------------------


def test_matched_reply_yields_matchoutcome_true(reporter: FakeReporter) -> None:
    with _server(_reply_with(_MATCHED_REPLY)) as plugin:
        sink = _make_sink(plugin.port, reporter)
        outcome = sink.send("Tower, request taxi")

    assert outcome == MatchOutcome(matched=True, resolved_command="Tower, request taxi")
    assert reporter.errors() == []
    # v1 UI surfacing: a same-text match reports "VoiceAttack matched: <command>".
    assert any("VoiceAttack matched: Tower, request taxi" in msg for msg in reporter.messages())


def test_not_found_reply_yields_matchoutcome_false(reporter: FakeReporter) -> None:
    with _server(_reply_with(_NOT_FOUND_REPLY)) as plugin:
        sink = _make_sink(plugin.port, reporter)
        outcome = sink.send("does not exist")

    assert outcome == MatchOutcome(matched=False, resolved_command=None)
    assert reporter.errors() == []
    # v1 UI surfacing: an unmatched command is surfaced as a warning, not silent.
    assert any(
        msg == "VoiceAttack has no command for: does not exist" and level is StatusLevel.WARNING
        for msg, level in reporter.reports
    )


def test_reply_split_across_packets_is_framed_to_newline(reporter: FakeReporter) -> None:
    """A reply dribbled out in pieces is reassembled until the newline (TCP may split)."""

    def responder(conn: socket.socket) -> None:
        half = len(_MATCHED_REPLY) // 2
        conn.sendall(_MATCHED_REPLY[:half])
        time.sleep(0.02)
        conn.sendall(_MATCHED_REPLY[half:])

    with _server(responder) as plugin:
        sink = _make_sink(plugin.port, reporter)
        outcome = sink.send("Tower, request taxi")

    assert outcome == MatchOutcome(matched=True, resolved_command="Tower, request taxi")


def test_reply_with_trailing_bytes_after_newline_is_framed_to_first_line(
    reporter: FakeReporter,
) -> None:
    """A single recv delivering the reply line AND trailing bytes parses only the first line.

    Pins the framing contract the dropped ``test_parse_reads_only_the_first_line`` used to
    cover: trailing data after the first ``\n`` must be ignored, not degrade the reply to
    ``None``.
    """
    payload = protocol.build_reply(True, "go") + b"trailing garbage"

    with _server(_reply_with(payload)) as plugin:
        sink = _make_sink(plugin.port, reporter)
        outcome = sink.send("go")

    assert outcome == MatchOutcome(matched=True, resolved_command="go")
    assert reporter.errors() == []


# -- degraded paths, all -> None ("unknown"), never an exception -------------------------


def test_slow_reply_past_timeout_yields_none(reporter: FakeReporter) -> None:
    # The plugin replies well after the sink's short read timeout: best-effort -> None.
    with _server(_reply_slowly(_MATCHED_REPLY, delay=0.5)) as plugin:
        sink = _make_sink(plugin.port, reporter, read_timeout=0.1)
        outcome = sink.send("Tower, request taxi")

    assert outcome is None
    assert reporter.errors() == []  # a timeout is best-effort, not a reported error


def test_garbage_reply_yields_none(reporter: FakeReporter) -> None:
    with _server(_reply_with(b"{not valid json at all\n")) as plugin:
        sink = _make_sink(plugin.port, reporter)
        outcome = sink.send("Tower, request taxi")

    assert outcome is None
    assert reporter.errors() == []


def test_accept_then_close_without_reply_yields_none(reporter: FakeReporter) -> None:
    with _server(_close_without_reply) as plugin:
        sink = _make_sink(plugin.port, reporter)
        outcome = sink.send("Tower, request taxi")

    assert outcome is None
    assert reporter.errors() == []  # EOF with no reply is unknown, not an error


def test_connection_refused_yields_none_and_reports_error(reporter: FakeReporter) -> None:
    # Bind+close a socket to obtain a port guaranteed to have nothing listening.
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.bind((_HOST, 0))
        dead_port = probe.getsockname()[1]

    sink = _make_sink(dead_port, reporter)
    outcome = sink.send("Tower, request taxi")

    assert outcome is None  # a network error never raises into the caller
    assert reporter.errors()  # ... but it IS surfaced to the user as an error


# -- fire-and-forget: await_result=False never reads, returns None fast ------------------


def test_fire_and_forget_does_not_read_reply(reporter: FakeReporter) -> None:
    # The plugin would reply "matched", but with await_result=False the sink must NOT read it
    # and must return None (legacy behaviour, zero added latency).
    with _server(_reply_with(_MATCHED_REPLY)) as plugin:
        sink = _make_sink(plugin.port, reporter, await_result=False)
        started = time.monotonic()
        outcome = sink.send("Tower, request taxi")
        elapsed = time.monotonic() - started
        # Give the server thread a moment to record the request it accepted.
        time.sleep(0.05)
        requests = list(plugin.requests)

    assert outcome is None
    assert requests == [b"Tower, request taxi"]  # the command WAS sent (request received)
    assert elapsed < 0.2  # returned promptly, no read-timeout wait
    # Success (not error) was reported even though no reply was read.
    assert reporter.errors() == []
