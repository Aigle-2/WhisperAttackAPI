"""Unit tests for the commands-window pure helpers (sort + filter).

The Tk widgets in :mod:`vaivox.infrastructure.ui.commands_window` need a display, but the
list-building logic is pure and is what matters: alphabetical ordering, de-duplication, and
the live search filter. These pin that logic without a UI.
"""

from __future__ import annotations

from vaivox.infrastructure.ui.commands_window import (
    filter_command_entries,
    filter_commands,
    sort_command_entries,
    sort_commands,
)
from vaivox.infrastructure.vocabulary.command_catalog import CommandCatalogEntry


def test_sort_commands_orders_case_insensitively_ascending():
    commands = ["Wheel chocks", "action RTB", "Bingo fuel", "Action CHECK IN"]

    # Case-insensitive: "action check in" < "action rtb" < "bingo fuel" < "wheel chocks".
    assert sort_commands(commands) == [
        "Action CHECK IN",
        "action RTB",
        "Bingo fuel",
        "Wheel chocks",
    ]


def test_sort_commands_dedupes_case_insensitively_keeping_first_casing():
    commands = ["Action CHECK IN", "action check in", "RTB", "rtb"]

    assert sort_commands(commands) == ["Action CHECK IN", "RTB"]


def test_sort_commands_drops_blank_and_whitespace_entries():
    commands = ["  ", "", "  Push Pontiac  ", "Abort"]

    assert sort_commands(commands) == ["Abort", "Push Pontiac"]


def test_filter_commands_blank_query_returns_everything():
    commands = ["Abort", "Bingo fuel", "Check in"]

    assert filter_commands(commands, "") == commands
    assert filter_commands(commands, "   ") == commands


def test_filter_commands_matches_substring_case_insensitively_in_order():
    commands = ["Action CHECK IN", "Bingo fuel", "Check fire", "Wheel chocks"]

    assert filter_commands(commands, "check") == ["Action CHECK IN", "Check fire"]
    assert filter_commands(commands, "FUEL") == ["Bingo fuel"]


def test_filter_commands_no_match_returns_empty():
    assert filter_commands(["Abort", "RTB"], "zzz") == []


def test_sort_command_entries_keeps_metadata_while_deduping():
    entries = [
        CommandCatalogEntry("Ground Power Connect", aircraft=("F-4E",)),
        CommandCatalogEntry("ground power connect", groups=("F-4E AI WSO | Ground Crew",)),
        "Abort",
    ]

    sorted_entries = sort_command_entries(entries)

    assert [entry.phrase for entry in sorted_entries] == ["Abort", "Ground Power Connect"]
    scoped = sorted_entries[1]
    assert scoped.aircraft == ("F-4E",)
    assert scoped.groups == ("F-4E AI WSO | Ground Crew",)


def test_filter_command_entries_can_show_only_current_aircraft_scope():
    entries = [
        CommandCatalogEntry("External Power Off", groups=("AI Comms | Crew",)),
        CommandCatalogEntry(
            "Ground Power Connect",
            groups=("F-4E AI WSO | Ground Crew",),
            aircraft=("F-4E",),
        ),
        CommandCatalogEntry(
            "Ground Power Disconnect",
            groups=("F-4E AI WSO | Ground Crew",),
            aircraft=("F-4E",),
        ),
        CommandCatalogEntry("Ground Power On", groups=("AI Comms | Crew",)),
        CommandCatalogEntry("Radar Scan High", aircraft=("F-14",)),
    ]

    filtered = filter_command_entries(
        entries,
        "power",
        current_aircraft="F-4E-45MC",
        include_current=True,
        include_general=False,
        include_other=False,
        scope_filter_enabled=True,
    )

    assert [entry.phrase for entry in filtered] == [
        "Ground Power Connect",
        "Ground Power Disconnect",
    ]


def test_filter_command_entries_can_include_general_commands():
    entries = [
        CommandCatalogEntry("Ground Power Connect", aircraft=("F-4E",)),
        CommandCatalogEntry("Ground Power On"),
    ]

    filtered = filter_command_entries(
        entries,
        "power",
        current_aircraft="F-4E-45MC",
        include_current=True,
        include_general=True,
        include_other=False,
        scope_filter_enabled=True,
    )

    assert [entry.phrase for entry in filtered] == ["Ground Power Connect", "Ground Power On"]
