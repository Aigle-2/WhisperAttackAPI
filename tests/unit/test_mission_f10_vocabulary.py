"""Unit tests for the mission-scoped VAICOM F10 vocabulary overlay."""

from __future__ import annotations

from vaivox.domain.commands.model import (
    CommandResolutionDecision,
    MissionMenuEntry,
    VaicomF10Action,
)
from vaivox.domain.commands.resolver import CommandSurfaceResolver
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


def test_parse_f10_surfaces_preserves_diagnostics_but_not_log_dispatch_index() -> None:
    text = "\n".join(
        [
            "Mission title: AI ATC Nellis, Menu name: Other",
            "Set menu F10 item: Action FLEX NORTH, ActionIndex: 3, Command ID: 20042",
        ]
    )

    [surface] = parse_f10_surfaces(text)

    assert surface.label == "FLEX NORTH"
    assert surface.aliases == ("Action FLEX NORTH",)
    assert surface.source == "mission_f10"
    assert surface.scope == "mission"
    target = surface.dispatch_target
    assert isinstance(target, VaicomF10Action)
    assert target.identifier == "Action FLEX NORTH"
    assert target.label == "FLEX NORTH"
    assert target.action_index is None
    assert target.command_id == 20042


def test_long_request_resolves_without_fabricated_request_aliases() -> None:
    text = "\n".join(
        [
            "Mission title: AI ATC Nellis, Menu name: Other",
            "Updating existing menu item: Action FLEX NORTH",
        ]
    )
    [surface] = parse_f10_surfaces(text)

    resolution = CommandSurfaceResolver([surface]).resolve("Request a FLEX NORTH")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.surface == surface
    assert resolution.matched_alias == "FLEX NORTH"


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


def test_latest_marker_with_no_f10_is_authoritative() -> None:
    text = "\n".join(
        [
            "Mission title: Foothold, Menu name: Other",
            "Set menu F10 item: Action CHECK IN, ActionIndex: 1, Command ID: 20002",
            "Mission title: Comms Menu, Menu name: Radio",
        ]
    )

    # Older entries must not leak into an authoritative empty current snapshot.
    assert parse_f10_phrases(text) == []


def test_parse_f10_phrases_uses_only_the_final_scan_block() -> None:
    text = "\n".join(
        [
            "Mission title: Old Mission, Menu name: Other",
            "Set menu F10 item: Action OLD COMMAND, ActionIndex: 1, Command ID: 20002",
            "Mission title: Current Mission, Menu name: Other",
            "Set menu F10 item: Action CHECK IN, ActionIndex: 1, Command ID: 20003",
            "Mission title: Current Mission, Menu name: Other",
            "Updating existing menu item: Action FENCE OUT",
        ]
    )

    assert parse_f10_phrases(text) == ["FENCE OUT"]


def test_current_update_lines_restore_existing_real_operator_commands() -> None:
    text = "\n".join(
        [
            "Mission title: AI ATC Nellis, Menu name: Other",
            "Processing menu item: FLEX NORTH, Identifier: Action FLEX NORTH",
            "Updating existing menu item: Action FLEX NORTH",
            "Processing menu item: MORMON MESA 8, Identifier: Action MORMON MESA 8",
            "Updating existing menu item: Action MORMON MESA 8",
            "Processing menu item: Squawk 2001, Identifier: Action Squawk 2001",
            "Updating existing menu item: Action Squawk 2001",
        ]
    )

    surfaces = parse_f10_surfaces(text)

    assert [surface.label for surface in surfaces] == [
        "FLEX NORTH",
        "MORMON MESA 8",
        "Squawk 2001",
    ]
    for surface in surfaces:
        target = surface.dispatch_target
        assert isinstance(target, VaicomF10Action)
        assert target.action_index is None
        assert target.command_id is None


def test_log_metadata_is_recovered_but_surface_remains_non_dispatchable() -> None:
    # Metadata may come from a Set line, but only the live listener can make it executable.
    text = "\n".join(
        [
            "Mission title: AI ATC Nellis, Menu name: Other",
            "Set menu F10 item: Action FLEX NORTH, ActionIndex: 3, Command ID: 20042",
            "Updating existing menu item: Action FLEX NORTH",
        ]
    )

    [surface] = parse_f10_surfaces(text)

    target = surface.dispatch_target
    assert isinstance(target, VaicomF10Action)
    assert target.action_index is None
    assert target.command_id == 20042


def test_earlier_mission_metadata_never_becomes_a_dispatch_index() -> None:
    # The real operator-log case: a historical Set line must not arm the current surface.
    text = "\n".join(
        [
            "Mission title: Earlier Session, Menu name: Other",
            "Set menu F10 item: Action FLEX NORTH, ActionIndex: 0, Command ID: 20086",
            "Mission title: tempMission, Menu name: Other",
            "Adding new menu item: Action FLEX NORTH",
        ]
    )

    [surface] = parse_f10_surfaces(text)

    target = surface.dispatch_target
    assert isinstance(target, VaicomF10Action)
    assert target.label == "FLEX NORTH"
    assert target.action_index is None
    assert target.command_id == 20086


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

    assert snapshot.phrases == ()
    assert len(snapshot.surfaces) == 1
    assert snapshot.surfaces[0].label == "Activate SA-6 Site"
    target = snapshot.surfaces[0].dispatch_target
    assert isinstance(target, VaicomF10Action)
    assert target.identifier == "Action Activate SA-6 Site"
    assert target.command_id == 20010  # retained as diagnostic metadata
    assert target.action_index is None  # historical log indices never dispatch
    assert snapshot.surfaces[0].available is False
    assert snapshot.display_phrases == ("Activate SA-6 Site — unavailable",)
    assert snapshot.source == str(log)
    assert snapshot.reason == "no live F10 handshake"


def test_adapter_drops_a_previous_missions_commands_when_a_new_mission_loads(tmp_path) -> None:
    log = tmp_path / "VAICOMPRO.log"
    log.write_text(
        "Mission title: Old Mission, Menu name: Other\n"
        "Set menu F10 item: Action OLD COMMAND, ActionIndex: 1, Command ID: 20001\n",
        encoding="utf-8",
    )
    adapter = VaicomF10MissionVocabulary(str(log))

    assert adapter.load().display_phrases == ("OLD COMMAND — unavailable",)

    # A new mission imports its own F10 menu; the previous mission's command is dropped.
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(
            "Mission title: New Mission, Menu name: Other\n"
            "Set menu F10 item: Action NEW COMMAND, ActionIndex: 0, Command ID: 20002\n"
        )

    assert adapter.load().display_phrases == ("NEW COMMAND — unavailable",)


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


def test_live_menu_remains_dispatchable_when_vaicom_log_is_missing(tmp_path) -> None:
    entry = MissionMenuEntry("Voice command assist", 6, ("AI ATC", "Options"))
    snapshot = VaicomF10MissionVocabulary(
        str(tmp_path / "missing.log"), live_entries=lambda: (entry,)
    ).load()

    [surface] = snapshot.surfaces
    target = surface.dispatch_target

    assert snapshot.reason == "loaded"
    assert surface.available is True
    assert isinstance(target, VaicomF10Action)
    assert target.identifier == "Action Voice command assist"
    assert target.action_index == 6
    assert target.menu_path == ("AI ATC", "Options")


def test_live_index_overrides_the_log_action_index(tmp_path) -> None:
    # The live DCS menu (hook) is authoritative: it overrides the unreliable log index.
    log = tmp_path / "VAICOMPRO.log"
    log.write_text(
        "Mission title: AI ATC Nellis, Menu name: Other\n"
        "Set menu F10 item: Action FLEX NORTH, ActionIndex: 0, Command ID: 20086\n"
        "Adding new menu item: Action FLEX NORTH\n",
        encoding="utf-8",
    )

    adapter = VaicomF10MissionVocabulary(str(log), live_index=lambda: {"FLEX NORTH": 7})
    [surface] = adapter.load().surfaces

    target = surface.dispatch_target
    assert isinstance(target, VaicomF10Action)
    assert target.action_index == 7  # live value wins over the log's 0


def test_live_index_absent_label_rejects_the_log_fallback(tmp_path) -> None:
    log = tmp_path / "VAICOMPRO.log"
    log.write_text(
        "Mission title: AI ATC Nellis, Menu name: Other\n"
        "Set menu F10 item: Action FLEX NORTH, ActionIndex: 0, Command ID: 20086\n",
        encoding="utf-8",
    )

    # A live map that does not cover FLEX NORTH must not leak its historical index.
    adapter = VaicomF10MissionVocabulary(str(log), live_index=lambda: {"SOMETHING ELSE": 9})
    surfaces = adapter.load().surfaces
    flex = next(surface for surface in surfaces if surface.label == "FLEX NORTH")

    assert flex.dispatch_target.action_index is None
    assert flex.available is False


def test_empty_or_faulty_live_source_fails_closed(tmp_path) -> None:
    log = tmp_path / "VAICOMPRO.log"
    log.write_text(
        "Mission title: AI ATC Nellis, Menu name: Other\n"
        "Set menu F10 item: Action FLEX NORTH, ActionIndex: 0, Command ID: 20086\n",
        encoding="utf-8",
    )

    def unavailable() -> dict[str, int]:
        raise OSError("listener unavailable")

    for live_index in (lambda: {}, unavailable):
        [surface] = VaicomF10MissionVocabulary(str(log), live_index=live_index).load().surfaces
        target = surface.dispatch_target
        assert isinstance(target, VaicomF10Action)
        assert target.action_index is None
        assert target.command_id == 20086


def test_live_path_and_local_vaicom_aliases_build_an_active_surface(tmp_path) -> None:
    log = tmp_path / "VAICOMPRO.log"
    log.write_text(
        "Mission title: AI ATC Nellis, Menu name: Other\n"
        "Adding new menu item: Action Request Engine Start\n",
        encoding="utf-8",
    )
    entry = MissionMenuEntry(
        label="Request Engine Start",
        action_index=12,
        path=("AI ATC", "Ground"),
    )
    adapter = VaicomF10MissionVocabulary(
        str(log),
        live_entries=lambda: (entry,),
        action_aliases=lambda: {
            "action request engine start": (
                "Engine Start",
                "Request To Start Engines",
                "Requesting Start",
            )
        },
    )

    snapshot = adapter.load()
    [surface] = snapshot.surfaces
    target = surface.dispatch_target

    assert surface.available is True
    assert surface.semantic_aliases == (
        "Engine Start",
        "Request To Start Engines",
        "Requesting Start",
    )
    assert isinstance(target, VaicomF10Action)
    assert target.action_index == 12
    assert target.menu_path == ("AI ATC", "Ground")
    assert "Request To Start Engines" in snapshot.phrases
    assert "Request Engine Start — live (AI ATC / Ground)" in snapshot.display_phrases

    resolution = CommandSurfaceResolver(snapshot.surfaces).resolve(
        "Ground Uzi 6-1 request to start engines"
    )

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.matched_alias == "Request To Start Engines"


def test_inactive_dynamic_alias_is_rejected_instead_of_falling_through(tmp_path) -> None:
    log = tmp_path / "VAICOMPRO.log"
    log.write_text(
        "Mission title: AI ATC Nellis, Menu name: Other\n"
        "Adding new menu item: Action Request Takeoff\n",
        encoding="utf-8",
    )
    adapter = VaicomF10MissionVocabulary(
        str(log),
        live_entries=lambda: (),
        action_aliases=lambda: {"action request takeoff": ("Requesting Takeoff Clearance",)},
    )

    resolution = CommandSurfaceResolver(adapter.load().surfaces).resolve(
        "Requesting Takeoff Clearance"
    )

    assert resolution.decision is CommandResolutionDecision.REJECTED
    assert resolution.reason_code == "mission_action_inactive"
