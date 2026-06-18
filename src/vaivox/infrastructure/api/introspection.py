"""Minimal localhost introspection HTTP API (ADR-0010).

A read-only JSON API over the query use cases, built on the standard library so it
adds no dependency. It is **off by default**, binds 127.0.0.1 only, supports an
optional bearer token, and never mutates state. Phase 5 enriches it (telemetry /
vocab / metrics endpoints + the MCP adapter); here it is just status + dry-run.

Endpoints:
    GET  /healthz            -> ``{"status": "ok"}``
    GET  /status             -> the :class:`~vaivox.application.queries.StatusReport`
    POST /reconcile/dry-run  -> ``{"text": "..."}`` -> staged reconciliation result
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

from vaivox.application.queries import DescribeStatus, DryRunReconcile

_LOGGER = logging.getLogger(__name__)

DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8765


class _IntrospectionHTTPServer(ThreadingHTTPServer):
    """A threading HTTP server carrying the wired query use cases."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        describe_status: DescribeStatus,
        dry_run: DryRunReconcile,
        token: str | None,
    ) -> None:
        super().__init__(server_address, handler)
        self.describe_status = describe_status
        self.dry_run = dry_run
        self.token = token


class _IntrospectionRequestHandler(BaseHTTPRequestHandler):
    """Route introspection requests to the query use cases."""

    @property
    def _api(self) -> _IntrospectionHTTPServer:
        return cast("_IntrospectionHTTPServer", self.server)

    def _authorized(self) -> bool:
        token = self._api.token
        if not token:
            return True
        return self.headers.get("Authorization") == f"Bearer {token}"

    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if self.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path == "/status":
            self._send_json(HTTPStatus.OK, asdict(self._api.describe_status.execute()))
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if self.path != "/reconcile/dry-run":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length) if content_length else b""
        try:
            payload = json.loads(raw_body or b"{}")
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON body"})
            return

        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing 'text' field"})
            return

        self._send_json(HTTPStatus.OK, asdict(self._api.dry_run.execute(text)))

    def log_message(self, format: str, *args: object) -> None:
        _LOGGER.debug("introspection api: " + format, *args)


class IntrospectionServer:
    """Lifecycle wrapper around the localhost introspection HTTP server."""

    def __init__(
        self,
        describe_status: DescribeStatus,
        dry_run: DryRunReconcile,
        host: str = DEFAULT_API_HOST,
        port: int = DEFAULT_API_PORT,
        token: str | None = None,
    ) -> None:
        """Configure (but do not start) the introspection server.

        Args:
            describe_status: The status query use case.
            dry_run: The dry-run reconcile query use case.
            host: Bind address (localhost by default).
            port: Bind port (0 selects an ephemeral port).
            token: Optional bearer token required on every request.
        """
        self._describe_status = describe_status
        self._dry_run = dry_run
        self._host = host
        self._port = port
        self._token = token or None
        self._server: _IntrospectionHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> tuple[str, int]:
        """Start serving on a background daemon thread.

        Returns:
            The bound ``(host, port)``.
        """
        server = _IntrospectionHTTPServer(
            (self._host, self._port),
            _IntrospectionRequestHandler,
            self._describe_status,
            self._dry_run,
            self._token,
        )
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever, name="vaivox-introspection-api", daemon=True
        )
        self._thread.start()
        host, port = server.server_address[0], server.server_address[1]
        _LOGGER.info("Introspection API listening on http://%s:%s", host, port)
        return str(host), int(port)

    def stop(self) -> None:
        """Stop serving and release the socket."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
