"""Tests for the JSONL telemetry sink adapter (ADR-0006).

Exercises one-line-per-outcome serialization (including the nested ``MatchOutcome``),
append semantics, port conformance, and graceful degradation against a tmp data dir so
nothing touches the real per-user directory.
"""

from __future__ import annotations

import json

from vaivox.application.ports import TelemetrySink
from vaivox.domain.commands.model import DispatchOutcome
from vaivox.domain.telemetry.model import (
    CommandResolutionSummary,
    MatchOutcome,
    ReconciliationOutcome,
    SnapSummary,
)
from vaivox.infrastructure.telemetry.jsonl_sink import TELEMETRY_FILE, JsonlTelemetrySink


def _outcome(
    raw: str = "kobuletti tower", match: MatchOutcome | None = None
) -> ReconciliationOutcome:
    return ReconciliationOutcome(
        raw_text=raw,
        cleaned_text=raw,
        command_text="Kobuleti tower",
        sent_text="Kobuleti tower",
        destination="voiceattack",
        match=match,
    )


def test_sink_conforms_to_port(tmp_path) -> None:
    sink: TelemetrySink = JsonlTelemetrySink(str(tmp_path))
    assert isinstance(sink, TelemetrySink)


def test_record_writes_one_json_line_round_tripping(tmp_path) -> None:
    sink = JsonlTelemetrySink(str(tmp_path))

    sink.record(_outcome())

    log = tmp_path / TELEMETRY_FILE
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["raw_text"] == "kobuletti tower"
    assert record["command_text"] == "Kobuleti tower"
    assert record["sent_text"] == "Kobuleti tower"
    assert record["destination"] == "voiceattack"
    # Unknown match (no plugin return channel yet) round-trips as null.
    assert record["match"] is None


def test_record_serializes_nested_match_outcome(tmp_path) -> None:
    sink = JsonlTelemetrySink(str(tmp_path))

    sink.record(_outcome(match=MatchOutcome(matched=True, resolved_command="Kobuleti tower")))

    record = json.loads((tmp_path / TELEMETRY_FILE).read_text(encoding="utf-8").strip())
    assert record["match"] == {"matched": True, "resolved_command": "Kobuleti tower"}


def test_record_serializes_nested_snap_summary(tmp_path) -> None:
    sink = JsonlTelemetrySink(str(tmp_path))
    outcome = ReconciliationOutcome(
        raw_text="texaco request rejon",
        cleaned_text="texaco request rejon",
        command_text="texaco request rejon",
        sent_text="Texaco request rejoin",
        destination="voiceattack",
        snap=SnapSummary(
            decision="snapped",
            candidate="Texaco request rejoin",
            score=95.0,
            near_misses=(),
        ),
    )

    sink.record(outcome)

    record = json.loads((tmp_path / TELEMETRY_FILE).read_text(encoding="utf-8").strip())
    assert record["snap"] == {
        "decision": "snapped",
        "candidate": "Texaco request rejoin",
        "score": 95.0,
        "near_misses": [],
    }


def test_record_serializes_resolution_and_dispatch(tmp_path) -> None:
    sink = JsonlTelemetrySink(str(tmp_path))
    outcome = ReconciliationOutcome(
        raw_text="FLEX NORTH",
        cleaned_text="FLEX NORTH",
        command_text="FLEX NORTH",
        sent_text="Action FLEX NORTH",
        destination="vaicom_f10_action",
        match=MatchOutcome(matched=True, resolved_command="Action FLEX NORTH"),
        resolution=CommandResolutionSummary(
            decision="resolved",
            surface_id="mission_f10:action-flex-north",
            label="FLEX NORTH",
            source="mission_f10",
            target_kind="vaicom_f10_action",
            matched_alias="FLEX NORTH",
            score=100.0,
        ),
        dispatch=DispatchOutcome(
            target_kind="vaicom_f10_action",
            accepted=True,
            resolved_target="Action FLEX NORTH",
            detail="VAICOM F10 Action alias via VoiceAttack profile",
        ),
    )

    sink.record(outcome)

    record = json.loads((tmp_path / TELEMETRY_FILE).read_text(encoding="utf-8").strip())
    assert record["resolution"]["surface_id"] == "mission_f10:action-flex-north"
    assert record["match"] == {
        "matched": True,
        "resolved_command": "Action FLEX NORTH",
    }
    assert record["dispatch"] == {
        "target_kind": "vaicom_f10_action",
        "accepted": True,
        "resolved_target": "Action FLEX NORTH",
        "detail": "VAICOM F10 Action alias via VoiceAttack profile",
    }


def test_record_appends_one_line_per_outcome(tmp_path) -> None:
    sink = JsonlTelemetrySink(str(tmp_path))

    sink.record(_outcome(raw="first"))
    sink.record(_outcome(raw="second"))
    sink.record(_outcome(raw="third"))

    lines = (tmp_path / TELEMETRY_FILE).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["raw_text"] for line in lines] == ["first", "second", "third"]


def test_record_creates_missing_data_dir(tmp_path) -> None:
    nested = tmp_path / "does" / "not" / "exist"
    sink = JsonlTelemetrySink(str(nested))

    sink.record(_outcome())

    assert (nested / TELEMETRY_FILE).is_file()


def test_record_degrades_gracefully_on_bad_path(tmp_path) -> None:
    # A file standing where the data directory should be makes mkdir/open fail; the
    # sink must log and swallow it, never raising into the use case.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    sink = JsonlTelemetrySink(str(blocker / "telemetry_subdir"))

    sink.record(_outcome())  # must not raise


def test_record_preserves_unicode(tmp_path) -> None:
    sink = JsonlTelemetrySink(str(tmp_path))

    sink.record(_outcome(raw="café crête"))

    record = json.loads((tmp_path / TELEMETRY_FILE).read_text(encoding="utf-8").strip())
    assert record["raw_text"] == "café crête"
