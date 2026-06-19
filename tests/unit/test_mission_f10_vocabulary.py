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


def test_adapter_ignores_f10_already_in_the_log_at_startup(tmp_path) -> None:
    log = tmp_path / "VAICOMPRO.log"
    log.write_text(
        "Set menu F10 item: Action STALE FROM LAST SESSION, ActionIndex: 1, Command ID: 20001\n",
        encoding="utf-8",
    )

    # The first poll baselines on whatever is already there (a previous session) and pulls
    # nothing — a restart purges the overlay instead of re-pulling stale imports.
    snapshot = VaicomF10MissionVocabulary(str(log)).load()

    assert snapshot.phrases == ()
    assert snapshot.source == str(log)


def test_adapter_pulls_only_f10_appended_after_startup(tmp_path) -> None:
    log = tmp_path / "VAICOMPRO.log"
    log.write_text(
        "Set menu F10 item: Action STALE, ActionIndex: 1, Command ID: 20001\n",
        encoding="utf-8",
    )
    adapter = VaicomF10MissionVocabulary(str(log))

    assert adapter.load().phrases == ()  # baseline captured; pre-existing content ignored

    with open(log, "a", encoding="utf-8") as handle:
        handle.write(
            "Set menu F10 item: Action Activate SA-6 Site, ActionIndex: 2, Command ID: 20010\n"
        )
    snapshot = adapter.load()

    assert snapshot.phrases == ("Action Activate SA-6 Site",)
    assert snapshot.reason == "loaded"


def test_adapter_rereads_in_full_when_the_log_is_rotated(tmp_path) -> None:
    log = tmp_path / "VAICOMPRO.log"
    log.write_text("old session noise\n" * 50, encoding="utf-8")
    adapter = VaicomF10MissionVocabulary(str(log))

    assert adapter.load().phrases == ()  # baseline on the large stale log

    # VAICOM truncates its log for a new session; the shrunk file is re-read from the start.
    log.write_text(
        "Set menu F10 item: Action FENCE IN, ActionIndex: 0, Command ID: 20002\n",
        encoding="utf-8",
    )

    assert adapter.load().phrases == ("Action FENCE IN",)


def test_adapter_reports_no_install_when_auto_discovery_finds_nothing() -> None:
    snapshot = VaicomF10MissionVocabulary(discover=lambda: None).load()

    assert snapshot.phrases == ()
    assert snapshot.reason == "no VAICOM install found"
