"""Unit tests for the inbound control socket server guard rails."""

from __future__ import annotations

from threading import Event

from vaivox.application.ports import StatusLevel
from vaivox.infrastructure.inbound.control_server import ControlSocketServer


class FakeReporter:
    def __init__(self) -> None:
        self.lines = []

    def report(self, message, level=StatusLevel.INFO) -> None:
        self.lines.append((message, level))


def test_control_server_refuses_non_local_bind() -> None:
    reporter = FakeReporter()
    server = ControlSocketServer(
        on_start=lambda: None,
        on_stop=lambda: None,
        on_shutdown=lambda: None,
        is_recording=lambda: False,
        exit_event=Event(),
        reporter=reporter,
        on_startup=lambda: True,
        host="0.0.0.0",
        port=0,
    )

    server.run()

    assert reporter.lines == [
        (
            "Refusing to bind control socket to non-local host '0.0.0.0'; use 127.0.0.1/localhost.",
            StatusLevel.ERROR,
        )
    ]
