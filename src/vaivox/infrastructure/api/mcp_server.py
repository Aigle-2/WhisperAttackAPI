r"""MCP server adapter over the introspection query use cases (ADR-0010).

A thin Model Context Protocol server that gives agents (Claude Code, Codex) **native tool
access** to the *same* read query use cases as the HTTP introspection API
(:mod:`vaivox.infrastructure.api.introspection`) — status, dry-run reconcile, recent
events, metrics, vocabulary. It runs as a standalone stdio process (wired headlessly by
:mod:`vaivox.mcp_main`) and reads the persisted state under ``%LOCALAPPDATA%\VAIVOX``, so it
works whether or not the desktop app is running.

The ``mcp`` dependency is an **optional extra** (``uv sync --extra mcp``) and is imported
**lazily** inside :func:`build_mcp_server`: this module imports cleanly in the
dependency-light gate environment (the package smoke test imports every module), and the
tool bodies (:class:`IntrospectionTools`) are exercised without ``mcp`` installed.

The mutating actions (generate / reload / simulate) are intentionally **not** exposed here:
they act on the *live* in-app state (the running snapper, the VoiceAttack socket) that a
separate reader process does not own — they live on the embedded HTTP API instead.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from vaivox.application.queries import (
    DEFAULT_RECENT_LIMIT,
    ComputeMetrics,
    DescribeStatus,
    DescribeVocabulary,
    DryRunReconcile,
    ListRecentReconciliations,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class IntrospectionTools:
    """The read query use cases as MCP tool bodies (transport-agnostic, ``mcp``-free).

    Each method delegates to a query use case and flattens the dataclass result into a
    JSON-serializable dict, so the tool logic is unit-tested without the ``mcp`` dependency
    (only :func:`build_mcp_server` needs it).
    """

    def __init__(
        self,
        describe_status: DescribeStatus,
        dry_run: DryRunReconcile,
        recent_reconciliations: ListRecentReconciliations,
        compute_metrics: ComputeMetrics,
        describe_vocabulary: DescribeVocabulary,
    ) -> None:
        """Wire the same query use cases the HTTP introspection adapter uses."""
        self._describe_status = describe_status
        self._dry_run = dry_run
        self._recent_reconciliations = recent_reconciliations
        self._compute_metrics = compute_metrics
        self._describe_vocabulary = describe_vocabulary

    def status(self) -> dict[str, Any]:
        """Return VAIVOX version, recording flag, STT backend, and redacted config."""
        return asdict(self._describe_status.execute())

    def dry_run(self, text: str) -> dict[str, Any]:
        """Run ``text`` through the full reconciliation pipeline (no mic / VoiceAttack)."""
        return asdict(self._dry_run.execute(text))

    def recent_reconciliations(self, limit: int = DEFAULT_RECENT_LIMIT) -> dict[str, Any]:
        """Return the last ``limit`` recorded reconciliation events (oldest first)."""
        return asdict(self._recent_reconciliations.execute(limit))

    def metrics(self) -> dict[str, Any]:
        """Return live match / wrong-match / not-found / unknown / abstain counts + rates."""
        return asdict(self._compute_metrics.execute())

    def vocabulary(self) -> dict[str, Any]:
        """Return loaded vocabulary entries + usage stats, grouped by kind."""
        return asdict(self._describe_vocabulary.execute())


def build_mcp_server(tools: IntrospectionTools, name: str = "vaivox") -> FastMCP:
    """Build a FastMCP server registering the introspection tools (lazy ``mcp`` import).

    Args:
        tools: The introspection tool bodies to expose.
        name: The MCP server name advertised to clients.

    Returns:
        A configured ``FastMCP`` server (call ``.run(transport="stdio")`` to serve).
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(name)
    server.add_tool(
        tools.status,
        name="status",
        description="VAIVOX version, recording flag, STT backend, and redacted effective config.",
    )
    server.add_tool(
        tools.dry_run,
        name="dry_run",
        description=(
            "Run an utterance through the full reconciliation pipeline (cleanup + fuzzy "
            "correction) and return every stage, with no mic and no VoiceAttack. Args: text."
        ),
    )
    server.add_tool(
        tools.recent_reconciliations,
        name="recent_reconciliations",
        description="The last N reconciliation events (default 20), oldest first. Args: limit.",
    )
    server.add_tool(
        tools.metrics,
        name="metrics",
        description="Live match / wrong-match / not-found / unknown / abstain counts and rates.",
    )
    server.add_tool(
        tools.vocabulary,
        name="vocabulary",
        description="Loaded vocabulary entries + usage stats (hits / last_used), by kind.",
    )
    return server
