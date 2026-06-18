"""Unit tests for the MCP introspection tool bodies (ADR-0010).

The tools delegate to the same query use cases as the HTTP API and flatten each result to a
JSON-serializable dict. Exercised **without** the optional ``mcp`` dependency — only the
FastMCP registration in ``build_mcp_server`` needs it, so the tool logic stays testable in
the dependency-light gate environment.
"""

from __future__ import annotations

from datetime import datetime

from vaivox.application.queries import (
    ComputeMetrics,
    DescribeStatus,
    DescribeVocabulary,
    DryRunReconcile,
    ListRecentReconciliations,
)
from vaivox.domain.telemetry.model import MatchOutcome, ReconciliationOutcome
from vaivox.domain.vocabulary.model import (
    GovernedEntry,
    UsageStats,
    VocabularyEntry,
    VocabularyKind,
    VocabularyOrigin,
)
from vaivox.infrastructure.api.mcp_server import IntrospectionTools

FUZZY_WORDS = ["Kobuleti", "Senaki"]


class FakeRecorder:
    @property
    def is_recording(self):
        return False


class FakeConfig:
    def get_word_mappings(self):
        return {}

    def get_fuzzy_words(self):
        return FUZZY_WORDS

    def get_safe_configuration(self):
        return {"stt_backend": "elevenlabs", "elevenlabs_api_key": "<redacted>"}

    def get_stt_backend(self):
        return "elevenlabs"


class FakeTelemetryReader:
    def __init__(self, outcomes=None):
        self._outcomes = outcomes or []

    def recent(self, limit):
        if limit <= 0:
            return []
        return list(self._outcomes[-limit:])


class FakeVocabularyRepository:
    def __init__(self, entries=None):
        self._entries = entries or {}

    def load(self, kind):
        return list(self._entries.get(kind, []))


def _outcome(raw, matched=None, resolved=None):
    match = None if matched is None else MatchOutcome(matched=matched, resolved_command=resolved)
    return ReconciliationOutcome(
        raw_text=raw,
        cleaned_text=raw,
        command_text=raw,
        sent_text=raw,
        destination="voiceattack",
        match=match,
    )


def _tools(telemetry=None, vocabulary=None):
    config = FakeConfig()
    telemetry = telemetry or FakeTelemetryReader()
    vocabulary = vocabulary or FakeVocabularyRepository()
    return IntrospectionTools(
        DescribeStatus(FakeRecorder(), config),
        DryRunReconcile(config),
        ListRecentReconciliations(telemetry),
        ComputeMetrics(telemetry),
        DescribeVocabulary(vocabulary),
    )


def test_status_tool_returns_redacted_config():
    payload = _tools().status()

    assert payload["recording"] is False
    assert payload["stt_backend"] == "elevenlabs"
    assert payload["config"]["elevenlabs_api_key"] == "<redacted>"
    assert "version" in payload


def test_dry_run_tool_runs_the_pipeline():
    payload = _tools().dry_run("kobuletti tower")

    assert payload["raw_text"] == "kobuletti tower"
    assert payload["command_text"] == "Kobuleti tower"


def test_metrics_tool_aggregates_recorded_outcomes():
    telemetry = FakeTelemetryReader(
        [_outcome("a", matched=True, resolved="a"), _outcome("b", matched=False)]
    )

    payload = _tools(telemetry=telemetry).metrics()

    assert payload["total"] == 2
    assert payload["match"] == 1
    assert payload["not_found"] == 1


def test_recent_reconciliations_tool_respects_limit():
    telemetry = FakeTelemetryReader([_outcome(str(index)) for index in range(5)])

    payload = _tools(telemetry=telemetry).recent_reconciliations(limit=2)

    assert payload["limit"] == 2
    assert payload["count"] == 2
    assert [event["raw_text"] for event in payload["events"]] == ["3", "4"]


def test_vocabulary_tool_groups_by_kind():
    entry = VocabularyEntry(
        id="senaki",
        kind=VocabularyKind.FUZZY_WORD,
        term="Senaki",
        aliases=("sen-aki",),
        origin=VocabularyOrigin.DEFAULT,
    )
    governed = GovernedEntry(
        entry=entry, usage=UsageStats(last_used=datetime(2026, 6, 18, 12, 0, 0), hits=3)
    )
    vocabulary = FakeVocabularyRepository({VocabularyKind.FUZZY_WORD: [governed]})

    payload = _tools(vocabulary=vocabulary).vocabulary()

    assert payload["total"] == 1
    assert payload["by_kind"]["fuzzy_word"][0]["term"] == "Senaki"
    assert payload["by_kind"]["word_mapping"] == []
