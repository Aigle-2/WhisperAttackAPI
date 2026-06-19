"""Unit tests for the mission-scoped VAICOM F10 vocabulary overlay."""

from __future__ import annotations

from vaivox.domain.commands.model import VaicomF10Action
from vaivox.infrastructure.vocabulary.mission_f10 import (
    VaicomF10MissionVocabulary,
    parse_f10_phrases,
    parse_f10_surfaces,
)


def test_parse_f10_phrases_supports_current_vaicom_log_format() -> None:
    text = "\n".join(
        [
            "Mission title: Foothold, Menu name: Other",
            "Set menu F10 item: Action CHECK IN, ActionIndex: 1, Command ID: 20002",
            "Set menu F10 item: Action Push Pontiac, ActionIndex: 0, Command ID: 20031",
        ]
    )

    # VAICOM's "Action " is an internal identifier prefix, not the spoken command, so the
    # overlay keeps the bare menu name the user actually says (and VoiceAttack matches).
    assert parse_f10_phrases(text) == ["CHECK IN", "Push Pontiac"]


def test_parse_f10_surfaces_preserves_vaicom_dispatch_metadata() -> None:
    text = "\n".join(
        [
            "Mission title: AI ATC Nellis, Menu name: Other",
            "Set menu F10 item: Action FLEX NORTH, ActionIndex: 3, Command ID: 20042",
        ]
    )

    [surface] = parse_f10_surfaces(text)

    assert surface.label == "FLEX NORTH"
    assert surface.aliases[0] == "Action FLEX NORTH"
    assert surface.source == "mission_f10"
    assert surface.scope == "mission"
    target = surface.dispatch_target
    assert isinstance(target, VaicomF10Action)
    assert target.identifier == "Action FLEX NORTH"
    assert target.label == "FLEX NORTH"
    assert target.action_index == 3
    assert target.command_id == 20042


def test_parse_f10_phrases_strips_the_internal_action_prefix_keeping_single_words() -> None:
    text = "Set menu F10 item: Action Lion, ActionIndex: 1, Command ID: 20002"

    assert parse_f10_phrases(text) == ["Lion"]  # bare, single-word menu name is kept


def test_parse_f10_phrases_supports_legacy_vaicom_log_format() -> None:
    text = (
        "Setting menu F10 item Action COPY with actionIndex 0 as command 20001 "
        "Action COPY Setting menu F10 item Action FENCE IN with actionIndex 1 "
        "as command 20002 Action FENCE IN"
    )

    assert parse_f10_phrases(text) == ["COPY", "FENCE IN"]


def test_parse_f10_phrases_falls_back_to_whole_log_when_latest_marker_has_no_f10() -> None:
    text = "\n".join(
        [
            "Mission title: Foothold, Menu name: Other",
            "Set menu F10 item: Action CHECK IN, ActionIndex: 1, Command ID: 20002",
            "Mission title: Comms Menu, Menu name: Radio",
        ]
    )

    # The latest "Mission title:" marker ("Comms Menu") brackets no F10 items, but the log
    # does — so the whole-log fallback still surfaces the current commands.
    assert parse_f10_phrases(text) == ["CHECK IN"]


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

    assert parse_f10_phrases(text) == ["CHECK IN", "FENCE OUT"]


def test_adapter_loads_the_current_mission_f10_from_the_log(tmp_path) -> None:
    log = tmp_path / "VAICOMPRO.log"
    log.write_text(
        "Mission title: Foothold, Menu name: Other\n"
        "Set menu F10 item: Action Activate SA-6 Site, ActionIndex: 2, Command ID: 20010\n",
        encoding="utf-8",
    )

    # The current mission's commands are read even though they were logged before the
    # adapter was created (i.e. before a VAIVOX restart).
    snapshot = VaicomF10MissionVocabulary(str(log)).load()

    assert snapshot.phrases == ("Activate SA-6 Site",)
    assert len(snapshot.surfaces) == 1
    assert snapshot.surfaces[0].label == "Activate SA-6 Site"
    target = snapshot.surfaces[0].dispatch_target
    assert isinstance(target, VaicomF10Action)
    assert target.identifier == "Action Activate SA-6 Site"
    assert snapshot.source == str(log)
    assert snapshot.reason == "loaded"


def test_adapter_drops_a_previous_missions_commands_when_a_new_mission_loads(tmp_path) -> None:
    log = tmp_path / "VAICOMPRO.log"
    log.write_text(
        "Mission title: Old Mission, Menu name: Other\n"
        "Set menu F10 item: Action OLD COMMAND, ActionIndex: 1, Command ID: 20001\n",
        encoding="utf-8",
    )
    adapter = VaicomF10MissionVocabulary(str(log))

    assert adapter.load().phrases == ("OLD COMMAND",)

    # A new mission imports its own F10 menu; the previous mission's command is dropped.
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(
            "Mission title: New Mission, Menu name: Other\n"
            "Set menu F10 item: Action NEW COMMAND, ActionIndex: 0, Command ID: 20002\n"
        )

    assert adapter.load().phrases == ("NEW COMMAND",)


def test_adapter_populates_diagnostics_for_the_verbose_log(tmp_path) -> None:
    log = tmp_path / "VAICOMPRO.log"
    log.write_text(
        "Mission title: Foothold, Menu name: Other\n"
        "Set menu F10 item: Action CHECK IN, ActionIndex: 1, Command ID: 20002\n",
        encoding="utf-8",
    )

    diagnostics = VaicomF10MissionVocabulary(str(log)).load().diagnostics

    assert diagnostics is not None
    assert diagnostics.log_path == str(log)
    assert diagnostics.file_bytes > 0
    assert diagnostics.mission_markers == 1
    assert diagnostics.latest_mission == "Foothold"
    assert diagnostics.scoped_matches == 1
    assert diagnostics.deduped_phrases == 1
    assert diagnostics.fallback_used is False


def test_adapter_reports_no_install_when_auto_discovery_finds_nothing() -> None:
    snapshot = VaicomF10MissionVocabulary(discover=lambda: None).load()

    assert snapshot.phrases == ()
    assert snapshot.reason == "no VAICOM install found"
