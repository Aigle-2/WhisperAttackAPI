"""Tests for phrase-snapper configuration in the composition root."""

from __future__ import annotations

from vaivox.composition import (
    _merge_phrase_indexes,
    _mission_keyterms_from_phrases,
    build_phrase_snapper,
)
from vaivox.domain.reconciliation.snapper import SnapDecision
from vaivox.infrastructure.config.settings import VaivoxConfiguration
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
