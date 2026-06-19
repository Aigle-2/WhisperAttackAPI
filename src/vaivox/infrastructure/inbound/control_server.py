"""Control socket server: receive start/stop/shutdown commands from the plugin.

This is the inbound driver adapter — it listens on a localhost TCP socket and maps
each received command to a use case. It owns no domain logic; the legacy
``WhisperServer.run_server``/``handle_command`` loop moved here verbatim.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Callable
from ipaddress import ip_address
from threading import Event

from vaivox.application.ports import StatusLevel, StatusReporter

_LOGGER = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 65432
_LOCALHOST_NAMES = {"localhost"}


def _is_loopback_host(host: str) -> bool:
    """Return whether ``host`` names a local loopback bind address."""
    normalized = host.strip().lower()
    if normalized in _LOCALHOST_NAMES:
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


class ControlSocketServer:
    """Listen for control commands and dispatch them to the wired use cases."""

    def __init__(
        self,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_shutdown: Callable[[], None],
        is_recording: Callable[[], bool],
        exit_event: Event,
        reporter: StatusReporter,
        on_startup: Callable[[], bool] | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        """Wire the command callbacks and socket configuration.

        Args:
            on_start: Invoked for the ``start`` command.
            on_stop: Invoked for the ``stop`` command (and once at shutdown if a
                recording is still in progress).
            on_shutdown: Invoked for the ``shutdown`` command.
            is_recording: Returns whether a recording is currently active.
            exit_event: Signalled to stop the accept loop.
            reporter: The user-facing status reporter port.
            on_startup: Optional startup hook (e.g. load the STT backend); a falsy
                return aborts the server before it binds.
            host: The bind address.
            port: The bind port.
        """
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_shutdown = on_shutdown
        self._is_recording = is_recording
        self._exit_event = exit_event
        self._reporter = reporter
        self._on_startup = on_startup
        self._host = host
        self._port = port

    def handle_command(self, raw_command: str) -> None:
        """Dispatch a single received command string to the matching use case."""
        command = raw_command.strip().lower()
        _LOGGER.info("Received command: %s", command)
        if command == "start":
            self._on_start()
        elif command == "stop":
            self._on_stop()
        elif command == "shutdown":
            self._on_shutdown()
        else:
            _LOGGER.warning("Unknown command: %s", command)
            self._reporter.report(f"Unknown command: {command}", StatusLevel.WARNING)

    def run(self) -> None:
        """Run the startup hook, then accept and dispatch commands until shutdown."""
        if self._on_startup is not None and not self._on_startup():
            return
        if not _is_loopback_host(self._host):
            message = (
                "Refusing to bind control socket to non-local host "
                f"{self._host!r}; use 127.0.0.1/localhost."
            )
            _LOGGER.error(message)
            self._reporter.report(message, StatusLevel.ERROR)
            return

        _LOGGER.info("Server started and listening on %s:%s", self._host, self._port)
        self._reporter.report(
            f"Server started and listening on {self._host}:{self._port}", StatusLevel.SUCCESS
        )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.bind((self._host, self._port))
            server_socket.listen()
            server_socket.settimeout(1.0)

            while not self._exit_event.is_set():
                try:
                    conn, _ = server_socket.accept()
                    with conn:
                        data = conn.recv(1024).decode("utf-8")
                        if data:
                            self.handle_command(data)
                except TimeoutError:
                    continue
                except Exception as error:
                    _LOGGER.error("Socket error: %s", error)
                    self._reporter.report(f"Socket error: {error}", StatusLevel.ERROR)
                    continue

        if self._is_recording():
            self._on_stop()

        _LOGGER.info("Server has shut down cleanly.")
        self._reporter.report("Server has shut down cleanly.")
