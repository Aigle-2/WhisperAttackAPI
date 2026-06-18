r"""VAIVOX MCP server entry point — headless wiring for the stdio introspection server.

Wired as the ``vaivox-mcp`` console script (install with ``uv sync --extra mcp``). It
resolves the per-user data directory, builds the read query use cases over the *persisted*
state (config, telemetry log, vocabulary under ``%LOCALAPPDATA%\VAIVOX``), and serves them
over stdio via :func:`vaivox.infrastructure.api.mcp_server.build_mcp_server`.

It is a separate, read-only reader process (the desktop app need not be running). Logging
goes to **stderr** so the stdio MCP protocol on stdout stays clean. The live recording flag
is reported as ``False`` (a reader process does not capture audio); everything else is read
from the same files the app persists.
"""

from __future__ import annotations

import logging
import sys

from vaivox.application.queries import (
    ComputeMetrics,
    DescribeStatus,
    DescribeVocabulary,
    DryRunReconcile,
    ListRecentReconciliations,
)
from vaivox.infrastructure.api.mcp_server import IntrospectionTools, build_mcp_server
from vaivox.infrastructure.config.identity import VAIVOX
from vaivox.infrastructure.config.settings import VaivoxConfiguration
from vaivox.infrastructure.telemetry.jsonl_reader import JsonlTelemetryReader
from vaivox.infrastructure.vocabulary.jsonl_repository import JsonlVocabularyRepository
from vaivox.main import _ensure_src_on_path, _resolve_app_data_dir, _resolve_app_path

_LOGGER = logging.getLogger(__name__)


class _HeadlessRecorder:
    """A no-op recorder for the read-only MCP reader (a separate process never records)."""

    @property
    def is_recording(self) -> bool:
        """Always ``False`` — the reader process does not capture audio."""
        return False

    def start(self) -> None:
        """Unsupported in the reader process."""
        raise NotImplementedError("the MCP reader does not record audio")

    def stop(self) -> str | None:
        """Unsupported in the reader process."""
        raise NotImplementedError("the MCP reader does not record audio")


def build_tools(app_path: str, app_data_dir: str) -> IntrospectionTools:
    """Wire the read query use cases over the persisted per-user state (ADR-0010).

    Args:
        app_path: Directory holding the bundled default configuration.
        app_data_dir: The per-user data directory the app persists state into.

    Returns:
        The :class:`~vaivox.infrastructure.api.mcp_server.IntrospectionTools` bundle.
    """
    config = VaivoxConfiguration(app_path, app_data_dir)
    return IntrospectionTools(
        DescribeStatus(_HeadlessRecorder(), config),
        DryRunReconcile(config),
        ListRecentReconciliations(JsonlTelemetryReader(app_data_dir)),
        ComputeMetrics(JsonlTelemetryReader(app_data_dir)),
        DescribeVocabulary(JsonlVocabularyRepository(app_data_dir)),
    )


def main() -> None:
    """Resolve paths, wire the read tools, and serve the MCP server over stdio."""
    _ensure_src_on_path()
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    app_path = _resolve_app_path()
    app_data_dir = _resolve_app_data_dir(VAIVOX.data_dir_name)
    _LOGGER.info("Starting VAIVOX MCP server (data dir: %s)", app_data_dir)
    server = build_mcp_server(build_tools(app_path, app_data_dir))
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
