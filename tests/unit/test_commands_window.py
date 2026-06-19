"""Unit tests for the commands-window pure helpers (sort + filter).

The Tk widgets in :mod:`vaivox.infrastructure.ui.commands_window` need a display, but the
list-building logic is pure and is what matters: alphabetical ordering, de-duplication, and
the live search filter. These pin that logic without a UI.
"""

from __future__ import annotations

from vaivox.infrastructure.ui.commands_window import filter_commands, sort_commands


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
