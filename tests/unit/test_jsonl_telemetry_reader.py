"""Tests for the JSONL telemetry reader adapter (ADR-0010).

Exercises round-tripping with the sink (incl. nested ``MatchOutcome`` / ``SnapSummary``),
the most-recent-N tail semantics, port conformance, and graceful degradation (missing
file, malformed lines) against a tmp data dir so nothing touches the real per-user dir.
"""

from __future__ import annotations

from vaivox.application.ports import TelemetryReader
from vaivox.domain.commands.model import DispatchOutcome
from vaivox.domain.telemetry.model import (
    CommandResolutionSummary,
    MatchOutcome,
    ReconciliationOutcome,
    SnapSummary,
)
from vaivox.infrastructure.telemetry.jsonl_reader import JsonlTelemetryReader
from vaivox.infrastructure.telemetry.jsonl_sink import TELEMETRY_FILE, JsonlTelemetrySink


def _outcome(raw: str) -> ReconciliationOutcome:
    return ReconciliationOutcome(
        raw_text=raw,
        cleaned_text=raw,
        command_text=raw,
        sent_text=raw,
        destination="voiceattack",
    )


def test_reader_conforms_to_port(tmp_path) -> None:
    reader: TelemetryReader = JsonlTelemetryReader(str(tmp_path))
    assert isinstance(reader, TelemetryReader)


def test_recent_returns_empty_when_log_absent(tmp_path) -> None:
    reader = JsonlTelemetryReader(str(tmp_path))
    assert reader.recent(10) == []


def test_recent_returns_empty_for_non_positive_limit(tmp_path) -> None:
    JsonlTelemetrySink(str(tmp_path)).record(_outcome("only"))
    reader = JsonlTelemetryReader(str(tmp_path))
    assert reader.recent(0) == []
    assert reader.recent(-3) == []


def test_recent_round_trips_sink_records(tmp_path) -> None:
    sink = JsonlTelemetrySink(str(tmp_path))
    sink.record(
        ReconciliationOutcome(
            raw_text="texaco request rejon",
            cleaned_text="texaco request rejon",
            command_text="texaco request rejon",
            sent_text="Texaco request rejoin",
            destination="voiceattack",
            match=MatchOutcome(matched=True, resolved_command="Texaco request rejoin"),
            snap=SnapSummary(
                decision="snapped",
                candidate="Texaco request rejoin",
                score=95.0,
                near_misses=(("Texaco request fuel", 71.0),),
            ),
            resolution=CommandResolutionSummary(
                decision="resolved",
                surface_id="voiceattack:texaco-request-rejoin",
                label="Texaco request rejoin",
                source="voiceattack",
                target_kind="voiceattack",
                matched_alias="Texaco request rejoin",
                score=100.0,
            ),
            dispatch=DispatchOutcome(
                target_kind="voiceattack",
                accepted=True,
                resolved_target="Texaco request rejoin",
            ),
        )
    )

    [outcome] = JsonlTelemetryReader(str(tmp_path)).recent(10)

    assert outcome.raw_text == "texaco request rejon"
    assert outcome.sent_text == "Texaco request rejoin"
    assert outcome.match == MatchOutcome(matched=True, resolved_command="Texaco request rejoin")
    assert outcome.snap is not None
    assert outcome.snap.decision == "snapped"
    assert outcome.snap.near_misses == (("Texaco request fuel", 71.0),)
    assert outcome.resolution == CommandResolutionSummary(
        decision="resolved",
        surface_id="voiceattack:texaco-request-rejoin",
        label="Texaco request rejoin",
        source="voiceattack",
        target_kind="voiceattack",
        matched_alias="Texaco request rejoin",
        score=100.0,
    )
    assert outcome.dispatch == DispatchOutcome(
        target_kind="voiceattack",
        accepted=True,
        resolved_target="Texaco request rejoin",
    )


def test_recent_returns_last_n_oldest_first(tmp_path) -> None:
    sink = JsonlTelemetrySink(str(tmp_path))
    for index in range(5):
        sink.record(_outcome(str(index)))

    outcomes = JsonlTelemetryReader(str(tmp_path)).recent(3)

    assert [outcome.raw_text for outcome in outcomes] == ["2", "3", "4"]


def test_recent_returns_all_when_limit_exceeds_count(tmp_path) -> None:
    sink = JsonlTelemetrySink(str(tmp_path))
    sink.record(_outcome("first"))
    sink.record(_outcome("second"))

    outcomes = JsonlTelemetryReader(str(tmp_path)).recent(100)

    assert [outcome.raw_text for outcome in outcomes] == ["first", "second"]


def test_recent_skips_malformed_lines(tmp_path) -> None:
    log = tmp_path / TELEMETRY_FILE
    log.write_text(
        "\n".join(
            [
                "not json at all",
                '{"raw_text": "missing other fields"}',
                "[1, 2, 3]",  # JSON, but not an object
                '{"raw_text":"ok","cleaned_text":"ok","command_text":"ok",'
                '"sent_text":"ok","destination":"voiceattack","match":null,"snap":null}',
                "",
            ]
        ),
        encoding="utf-8",
    )

    outcomes = JsonlTelemetryReader(str(tmp_path)).recent(10)

    assert len(outcomes) == 1
    assert outcomes[0].raw_text == "ok"
    assert outcomes[0].match is None
    assert outcomes[0].snap is None
