"""Integration tests for the localhost introspection API (ADR-0010).

Start the real stdlib HTTP server on an ephemeral port and exercise it over HTTP —
status, metrics, reconciliations, vocabulary, dry-run reconcile, auth, and error paths
— with in-memory fakes for the ports.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime

import pytest

from vaivox.application.queries import (
    ComputeMetrics,
    DescribeStatus,
    DescribeVocabulary,
    DryRunReconcile,
    ListRecentReconciliations,
)
from vaivox.domain.telemetry.model import MatchOutcome, ReconciliationOutcome, SnapSummary
from vaivox.domain.vocabulary.model import (
    GovernedEntry,
    UsageStats,
    VocabularyEntry,
    VocabularyKind,
    VocabularyOrigin,
)
from vaivox.infrastructure.api.introspection import IntrospectionServer

FUZZY_WORDS = ["Kobuleti", "Senaki"]


class FakeRecorder:
    def __init__(self, recording=False):
        self._recording = recording

    @property
    def is_recording(self):
        return self._recording


class FakeConfig:
    def get_word_mappings(self):
        return {}

    def get_fuzzy_words(self):
        return FUZZY_WORDS

    def get_safe_configuration(self):
        return {"stt_backend": "elevenlabs", "elevenlabs_api_key": "<redacted>"}

    def get_stt_backend(self):
        return "elevenlabs"


def _outcome(raw, matched=None, resolved=None, snap_decision=None):
    match = None if matched is None else MatchOutcome(matched=matched, resolved_command=resolved)
    snap = None if snap_decision is None else SnapSummary(decision=snap_decision)
    return ReconciliationOutcome(
        raw_text=raw,
        cleaned_text=raw,
        command_text=raw,
        sent_text=raw,
        destination="voiceattack",
        match=match,
        snap=snap,
    )


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


def _make_server(token=None, telemetry=None, vocabulary=None):
    config = FakeConfig()
    telemetry = telemetry or FakeTelemetryReader()
    vocabulary = vocabulary or FakeVocabularyRepository()
    return IntrospectionServer(
        DescribeStatus(FakeRecorder(), config),
        DryRunReconcile(config),
        ListRecentReconciliations(telemetry),
        ComputeMetrics(telemetry),
        DescribeVocabulary(vocabulary),
        host="127.0.0.1",
        port=0,
        token=token,
    )


def _get(host, port, path, token=None):
    request = urllib.request.Request(f"http://{host}:{port}{path}")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post(host, port, path, body, token=None):
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(f"http://{host}:{port}{path}", data=data, method="POST")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


@pytest.fixture
def server():
    instance = _make_server()
    host, port = instance.start()
    yield host, port
    instance.stop()


def _running_server(**kwargs):
    instance = _make_server(**kwargs)
    host, port = instance.start()
    return instance, host, port


def test_healthz_returns_ok(server):
    host, port = server

    status, payload = _get(host, port, "/healthz")

    assert status == 200
    assert payload == {"status": "ok"}


def test_status_reports_state_with_redacted_config(server):
    host, port = server

    status, payload = _get(host, port, "/status")

    assert status == 200
    assert payload["recording"] is False
    assert payload["stt_backend"] == "elevenlabs"
    assert payload["config"]["elevenlabs_api_key"] == "<redacted>"
    assert "version" in payload


def test_dry_run_reconcile_returns_pipeline_stages(server):
    host, port = server

    status, payload = _post(host, port, "/reconcile/dry-run", {"text": "kobuletti tower"})

    assert status == 200
    assert payload["raw_text"] == "kobuletti tower"
    assert payload["command_text"] == "Kobuleti tower"


def test_dry_run_without_text_is_bad_request(server):
    host, port = server

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(host, port, "/reconcile/dry-run", {"not_text": 1})

    assert exc_info.value.code == 400


def test_unknown_path_is_not_found(server):
    host, port = server

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get(host, port, "/does-not-exist")

    assert exc_info.value.code == 404


def test_metrics_aggregates_recorded_outcomes():
    telemetry = FakeTelemetryReader(
        [
            _outcome("a", matched=True, resolved="a"),  # true match
            _outcome("b", matched=True, resolved="c"),  # wrong match
            _outcome("d", matched=False),  # not found
            _outcome("e"),  # unknown (no return channel)
            # Abstain is independent of the match band: this event also has no reported
            # match, so it counts in both ``abstain`` and ``unknown``.
            _outcome("f", snap_decision="abstained"),
        ]
    )
    instance, host, port = _running_server(telemetry=telemetry)
    try:
        status, payload = _get(host, port, "/metrics")
    finally:
        instance.stop()

    assert status == 200
    assert payload["total"] == 5
    assert payload["match"] == 1
    assert payload["wrong_match"] == 1
    assert payload["not_found"] == 1
    assert payload["unknown"] == 2
    assert payload["abstain"] == 1
    assert payload["match_rate"] == 0.2


def test_reconciliations_returns_recent_events_with_limit():
    telemetry = FakeTelemetryReader([_outcome(str(index)) for index in range(5)])
    instance, host, port = _running_server(telemetry=telemetry)
    try:
        status, payload = _get(host, port, "/reconciliations?limit=2")
    finally:
        instance.stop()

    assert status == 200
    assert payload["limit"] == 2
    assert payload["count"] == 2
    assert [event["raw_text"] for event in payload["events"]] == ["3", "4"]


def test_reconciliations_default_limit_when_unspecified():
    telemetry = FakeTelemetryReader([_outcome("only")])
    instance, host, port = _running_server(telemetry=telemetry)
    try:
        status, payload = _get(host, port, "/reconciliations")
    finally:
        instance.stop()

    assert status == 200
    assert payload["limit"] == 20
    assert payload["count"] == 1


def test_reconciliations_rejects_bad_limit():
    instance, host, port = _running_server()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _get(host, port, "/reconciliations?limit=nope")
    finally:
        instance.stop()

    assert exc_info.value.code == 400


def test_vocabulary_reports_entries_grouped_by_kind():
    entry = VocabularyEntry(
        id="senaki",
        kind=VocabularyKind.FUZZY_WORD,
        term="Senaki",
        aliases=("sen-aki",),
        origin=VocabularyOrigin.DEFAULT,
    )
    governed = GovernedEntry(
        entry=entry, usage=UsageStats(last_used=datetime(2026, 6, 18, 12, 0, 0), hits=7)
    )
    vocabulary = FakeVocabularyRepository({VocabularyKind.FUZZY_WORD: [governed]})
    instance, host, port = _running_server(vocabulary=vocabulary)
    try:
        status, payload = _get(host, port, "/vocabulary")
    finally:
        instance.stop()

    assert status == 200
    assert payload["total"] == 1
    fuzzy = payload["by_kind"]["fuzzy_word"]
    assert fuzzy[0]["id"] == "senaki"
    assert fuzzy[0]["term"] == "Senaki"
    assert fuzzy[0]["hits"] == 7
    assert fuzzy[0]["origin"] == "default"
    assert payload["by_kind"]["word_mapping"] == []


def test_bearer_token_is_enforced_when_configured():
    instance = _make_server(token="s3cret")
    host, port = instance.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _get(host, port, "/status")
        assert exc_info.value.code == 401

        status, _payload = _get(host, port, "/status", token="s3cret")
        assert status == 200
    finally:
        instance.stop()
