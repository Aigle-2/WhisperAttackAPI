"""Tests for phrase-snapper configuration in the composition root."""

from __future__ import annotations

from vaivox.composition import (
    _core_command_entries,
    _merge_phrase_indexes,
    _mission_keyterms_from_phrases,
    _voiceattack_surfaces,
    build_phrase_snapper,
)
from vaivox.domain.reconciliation.snapper import SnapDecision
from vaivox.infrastructure.config.settings import VaivoxConfiguration
from vaivox.infrastructure.ui.commands_window import (
    display_command_entry,
    filter_command_entries,
    sort_command_entries,
)
from vaivox.infrastructure.vocabulary.command_catalog import CommandCatalogEntry
from vaivox.infrastructure.vocabulary.phrase_index import PHRASE_INDEX_FILE


class FakeRecorder:
    @property
    def is_recording(self):
        return False


class FakeReporter:
    def __init__(self):
        self.lines = []

    def report(self, message, level=None):
        self.lines.append((message, level))


def test_snap_threshold_setting_can_be_changed_and_reapplied(tmp_path) -> None:
    app_dir = tmp_path / "app"
    data_dir = tmp_path / "data"
    app_dir.mkdir()
    data_dir.mkdir()
    (app_dir / "settings.cfg").write_text(
        "snap_high=90.0\nsnap_low=60.0\nsnap_margin=15.0\n",
        encoding="utf-8",
    )
    (data_dir / PHRASE_INDEX_FILE).write_text("Remove the Wheelchocks\n", encoding="utf-8")
    config = VaivoxConfiguration(str(app_dir), str(data_dir))
    snapper = build_phrase_snapper(config, FakeRecorder(), FakeReporter())
    command = "Chief remove the wheel chocks"

    assert snapper.snap(command).decision is SnapDecision.ABSTAINED

    config.set_custom_settings({"snap_high": "88.0"})
    applied = snapper.rebuild_current()

    assert applied is True
    assert snapper.snap(command).decision is SnapDecision.SNAPPED


def test_phrase_index_merge_keeps_permanent_and_mission_entries_distinct() -> None:
    assert _merge_phrase_indexes(
        ["Texaco request rejoin", "Action CHECK IN"],
        ["Action CHECK IN", "Action FENCE OUT"],
    ) == ["Texaco request rejoin", "Action CHECK IN", "Action FENCE OUT"]


def test_mission_keyterms_include_action_and_raw_menu_phrase() -> None:
    assert _mission_keyterms_from_phrases(["Action CHECK IN"]) == ["Action CHECK IN", "CHECK IN"]


def test_voiceattack_surfaces_ignore_keyword_only_aliases() -> None:
    surfaces = _voiceattack_surfaces(
        [
            CommandCatalogEntry("Tune TACAN", sources=("keywords.html",)),
            CommandCatalogEntry(
                "[Set; Select] TACAN [channel] [0..9]",
                aircraft=("F-4E",),
                sources=("VAICOM F-4E WSO.vap",),
            ),
        ]
    )

    assert [surface.label for surface in surfaces] == ["[Set; Select] TACAN [channel] [0..9]"]
    assert surfaces[0].scope == "F-4E"


def test_core_command_entries_keep_keyword_only_snap_phrases() -> None:
    entries = [
        CommandCatalogEntry(
            "Ground Power Connect",
            aircraft=("F-4E",),
            sources=("keywords.txt", "keywords.html"),
        ),
        CommandCatalogEntry(
            "Ground Power Disconnect",
            aircraft=("F-4E",),
            sources=("keywords.txt", "keywords.html"),
        ),
        CommandCatalogEntry("Action CHECK IN", sources=("VAICOM PRO for DCS World.vap",)),
    ]

    core_entries = _core_command_entries(entries, mission_phrases=("Action CHECK IN",))

    assert [entry.phrase for entry in core_entries] == [
        "Ground Power Connect",
        "Ground Power Disconnect",
    ]


def test_core_commands_window_data_keeps_f4_ground_power_without_tk() -> None:
    entries = [
        CommandCatalogEntry("External Power On"),
        CommandCatalogEntry("Ground Power Connect", aircraft=("F-4E",), sources=("keywords.html",)),
        CommandCatalogEntry(
            "Ground Power Disconnect",
            aircraft=("F-4E",),
            sources=("keywords.txt", "keywords.html"),
        ),
        CommandCatalogEntry("Ground Power On", sources=("VAICOM PRO for DCS World.vap",)),
        CommandCatalogEntry("Radar Scan High", aircraft=("F-14",), sources=("keywords.html",)),
    ]

    displayable = _core_command_entries(entries, mission_phrases=())
    visible = filter_command_entries(
        sort_command_entries(displayable),
        "power",
        current_aircraft="F-4E-45MC",
        include_current=True,
        include_general=False,
        include_other=False,
        scope_filter_enabled=True,
    )

    assert [display_command_entry(entry) for entry in visible] == [
        "Ground Power Connect",
        "Ground Power Disconnect",
    ]
