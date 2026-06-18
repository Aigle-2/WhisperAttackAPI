"""Tests for telemetry-sink selection in the composition root (ADR-0006).

Verifies the ``telemetry_enabled`` config flag selects the JSONL sink (default) or the
no-op sink, and that the JSONL sink is pointed at the per-user data directory.
"""

from __future__ import annotations

from vaivox.composition import build_telemetry_sink
from vaivox.infrastructure.config.settings import VaivoxConfiguration
from vaivox.infrastructure.telemetry.jsonl_sink import TELEMETRY_FILE, JsonlTelemetrySink
from vaivox.infrastructure.telemetry.null_sink import NullTelemetrySink


def _config(tmp_path, settings: str) -> VaivoxConfiguration:
    app_dir = tmp_path / "app"
    data_dir = tmp_path / "data"
    app_dir.mkdir()
    data_dir.mkdir()
    (app_dir / "settings.cfg").write_text(settings, encoding="utf-8")
    (app_dir / "word_mappings.txt").write_text("inter=Enter\n", encoding="utf-8")
    (app_dir / "fuzzy_words.txt").write_text("Kobuleti\n", encoding="utf-8")
    return VaivoxConfiguration(str(app_dir), str(data_dir))


def test_telemetry_enabled_by_default(tmp_path) -> None:
    # No telemetry_enabled key: the default (on) selects the JSONL sink.
    config = _config(tmp_path, "stt_backend=elevenlabs\n")

    sink = build_telemetry_sink(config)

    assert isinstance(sink, JsonlTelemetrySink)


def test_telemetry_explicitly_enabled_selects_jsonl_sink(tmp_path) -> None:
    config = _config(tmp_path, "telemetry_enabled=true\n")

    sink = build_telemetry_sink(config)

    assert isinstance(sink, JsonlTelemetrySink)


def test_telemetry_disabled_selects_null_sink(tmp_path) -> None:
    config = _config(tmp_path, "telemetry_enabled=false\n")

    sink = build_telemetry_sink(config)

    assert isinstance(sink, NullTelemetrySink)


def test_enabled_sink_writes_into_data_dir(tmp_path) -> None:
    from vaivox.domain.telemetry.model import ReconciliationOutcome

    config = _config(tmp_path, "telemetry_enabled=true\n")

    sink = build_telemetry_sink(config)
    sink.record(
        ReconciliationOutcome(
            raw_text="r",
            cleaned_text="c",
            command_text="cmd",
            sent_text="cmd",
            destination="voiceattack",
        )
    )

    assert (tmp_path / "data" / TELEMETRY_FILE).is_file()
