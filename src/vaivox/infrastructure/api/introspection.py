"""Minimal localhost introspection HTTP API (ADR-0010).

A read-only JSON API over the query use cases, built on the standard library so it
adds no dependency. It is **off by default**, binds 127.0.0.1 only, supports an
optional bearer token, and never mutates state. The MCP adapter and the gated mutating
actions are deferred fast-follows (see ``.claude/skills/vaivox-debug/SKILL.md``).

Endpoints:
    GET  /healthz            -> ``{"status": "ok"}``
    GET  /status             -> the :class:`~vaivox.application.queries.StatusReport`
    GET  /metrics            -> the :class:`~vaivox.application.queries.LiveMetrics`
    GET  /reconciliations    -> recent events (``?limit=N``, default 20)
    GET  /vocabulary         -> the :class:`~vaivox.application.queries.VocabularyReport`
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
from urllib.parse import parse_qs, urlsplit

from vaivox.application.queries import (
    ComputeMetrics,
    DescribeStatus,
    DescribeVocabulary,
    DryRunReconcile,
    ListRecentReconciliations,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8765

DEFAULT_RECONCILIATIONS_LIMIT = 20
MAX_RECONCILIATIONS_LIMIT = 500


class _IntrospectionHTTPServer(ThreadingHTTPServer):
    """A threading HTTP server carrying the wired query use cases."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        describe_status: DescribeStatus,
        dry_run: DryRunReconcile,
        recent_reconciliations: ListRecentReconciliations,
        compute_metrics: ComputeMetrics,
        describe_vocabulary: DescribeVocabulary,
        token: str | None,
    ) -> None:
        super().__init__(server_address, handler)
        self.describe_status = describe_status
        self.dry_run = dry_run
        self.recent_reconciliations = recent_reconciliations
        self.compute_metrics = compute_metrics
        self.describe_vocabulary = describe_vocabulary
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
        parts = urlsplit(self.path)
        path = parts.path
        if path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/status":
            self._send_json(HTTPStatus.OK, asdict(self._api.describe_status.execute()))
            return
        if path == "/metrics":
            self._send_json(HTTPStatus.OK, asdict(self._api.compute_metrics.execute()))
            return
        if path == "/vocabulary":
            self._send_json(HTTPStatus.OK, asdict(self._api.describe_vocabulary.execute()))
            return
        if path == "/reconciliations":
            self._handle_reconciliations(parts.query)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _handle_reconciliations(self, query: str) -> None:
        """Serve recent reconciliation events with an optional ``?limit=N`` cap."""
        limit = self._parse_limit(query)
        if limit is None:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid 'limit' parameter"})
            return
        self._send_json(HTTPStatus.OK, asdict(self._api.recent_reconciliations.execute(limit)))

    @staticmethod
    def _parse_limit(query: str) -> int | None:
        """Parse and clamp the ``limit`` query parameter.

        Returns:
            The clamped limit in ``[1, MAX_RECONCILIATIONS_LIMIT]``, the default when
            absent, or ``None`` when the supplied value is not a positive integer.
        """
        values = parse_qs(query).get("limit")
        if not values:
            return DEFAULT_RECONCILIATIONS_LIMIT
        try:
            limit = int(values[0])
        except ValueError:
            return None
        if limit < 1:
            return None
        return min(limit, MAX_RECONCILIATIONS_LIMIT)

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
        recent_reconciliations: ListRecentReconciliations,
        compute_metrics: ComputeMetrics,
        describe_vocabulary: DescribeVocabulary,
        host: str = DEFAULT_API_HOST,
        port: int = DEFAULT_API_PORT,
        token: str | None = None,
    ) -> None:
        """Configure (but do not start) the introspection server.

        Args:
            describe_status: The status query use case.
            dry_run: The dry-run reconcile query use case.
            recent_reconciliations: The recent-events query use case.
            compute_metrics: The live-metrics query use case.
            describe_vocabulary: The vocabulary query use case.
            host: Bind address (localhost by default).
            port: Bind port (0 selects an ephemeral port).
            token: Optional bearer token required on every request.
        """
        self._describe_status = describe_status
        self._dry_run = dry_run
        self._recent_reconciliations = recent_reconciliations
        self._compute_metrics = compute_metrics
        self._describe_vocabulary = describe_vocabulary
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
            self._recent_reconciliations,
            self._compute_metrics,
            self._describe_vocabulary,
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
