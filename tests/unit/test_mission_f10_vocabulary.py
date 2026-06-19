"""Unit tests for the mission-scoped VAICOM F10 vocabulary overlay."""

from __future__ import annotations

from vaivox.infrastructure.vocabulary.mission_f10 import (
    VaicomF10MissionVocabulary,
    parse_f10_phrases,
)


def test_parse_f10_phrases_supports_current_vaicom_log_format() -> None:
    text = "\n".join(
        [
            "Mission title: Foothold, Menu name: Other",
            "Set menu F10 item: Action CHECK IN, ActionIndex: 1, Command ID: 20002",
            "Set menu F10 item: Action Push Pontiac, ActionIndex: 0, Command ID: 20031",
        ]
    )

    assert parse_f10_phrases(text) == ["Action CHECK IN", "Action Push Pontiac"]


def test_parse_f10_phrases_supports_legacy_vaicom_log_format() -> None:
    text = (
        "Setting menu F10 item Action COPY with actionIndex 0 as command 20001 "
        "Action COPY Setting menu F10 item Action FENCE IN with actionIndex 1 "
        "as command 20002 Action FENCE IN"
    )

    assert parse_f10_phrases(text) == ["Action COPY", "Action FENCE IN"]


def test_parse_f10_phrases_uses_latest_mission_blocks_only() -> None:
    text = "\n".join(
        [
            "Mission title: Old Mission, Menu name: Other",
            "Set menu F10 item: Action OLD COMMAND, ActionIndex: 1, Command ID: 20002",
            "Mission title: Current Mission, Menu name: Other",
            "Set menu F10 item: Action CHECK IN, ActionIndex: 1, Command ID: 20003",
            "Mission title: Current Mission, Menu name: Other",
            "Set menu F10 item: Action FENCE OUT, ActionIndex: 2, Command ID: 20004",
        ]
    )

    assert parse_f10_phrases(text) == ["Action CHECK IN", "Action FENCE OUT"]


def test_adapter_loads_configured_vaicom_log(tmp_path) -> None:
    log = tmp_path / "VAICOMPRO.log"
    log.write_text(
        "Set menu F10 item: Action Activate SA-6 Site, ActionIndex: 2, Command ID: 20010",
        encoding="utf-8",
    )

    snapshot = VaicomF10MissionVocabulary(str(log)).load()

    assert snapshot.phrases == ("Action Activate SA-6 Site",)
    assert snapshot.source == str(log)
    assert snapshot.reason == "loaded"


def test_adapter_reports_no_install_when_auto_discovery_finds_nothing() -> None:
    snapshot = VaicomF10MissionVocabulary(discover=lambda: None).load()

    assert snapshot.phrases == ()
    assert snapshot.reason == "no VAICOM install found"
