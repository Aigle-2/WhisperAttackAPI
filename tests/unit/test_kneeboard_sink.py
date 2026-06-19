"""Unit tests for DCS kneeboard text formatting."""

from __future__ import annotations

from vaivox.infrastructure.kneeboard.sink import format_for_dcs_kneeboard, justify_line


def test_format_hard_wraps_word_longer_than_line() -> None:
    formatted = format_for_dcs_kneeboard("supercalifragilistic", 10)

    lines = formatted.splitlines()
    assert lines[:3] == ["supercalif", "ragilistic", "          "]
    assert all(len(line) == 10 for line in lines)


def test_justify_empty_line_is_blank() -> None:
    assert justify_line([], 5) == "     "
