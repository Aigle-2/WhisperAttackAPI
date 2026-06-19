"""DCS kneeboard sink: word-wrap a note, copy it, and trigger the in-game paste.

The wrapping logic (``format_for_dcs_kneeboard`` / ``justify_line``) is based on
BojotecX's WhisperKneeboard (https://github.com/BojoteX/KneeboardWhisper). The
clipboard/keyboard libraries are imported lazily so the module imports without them.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from vaivox.application.ports import StatusLevel, StatusReporter

_LOGGER = logging.getLogger(__name__)

_KNEEBOARD_HOTKEY = "ctrl+alt+p"


def format_for_dcs_kneeboard(text: str, line_length: int) -> str:
    """Word-wrap and justify ``text`` to fit a DCS kneeboard page.

    Args:
        text: The note text to format.
        line_length: The page width in display columns.

    Returns:
        The wrapped, justified text with a trailing blank line.
    """
    from wcwidth import wcswidth

    line_length = max(1, line_length)

    words = re.findall(r"\S+|\n", text)

    lines: list[str] = []
    current_words: list[str] = []
    current_len = 0

    for word in words:
        if word == "\n":
            if current_words:
                lines.append(" ".join(current_words).ljust(line_length))
                current_words = []
                current_len = 0
            else:
                lines.append(" " * line_length)
            continue

        for segment in _split_long_word(word, line_length):
            word_len = wcswidth(segment)
            # If adding the next word exceeds the line length, flush the current line.
            if current_words and current_len + word_len + len(current_words) > line_length:
                lines.append(justify_line(current_words, line_length))
                current_words = []
                current_len = 0

            if word_len >= line_length:
                if current_words:
                    lines.append(justify_line(current_words, line_length))
                    current_words = []
                    current_len = 0
                lines.append(segment.ljust(line_length))
            else:
                current_words.append(segment)
                current_len += word_len

    # Justify the last line (left-justified).
    if current_words:
        lines.append(" ".join(current_words).ljust(line_length))

    # Ensure the last line is completely blank.
    lines.append(" " * line_length)

    return "\n".join(lines)


def _split_long_word(word: str, line_length: int) -> list[str]:
    """Split an over-wide word into chunks that fit the kneeboard line width."""
    from wcwidth import wcwidth

    chunks: list[str] = []
    current = ""
    current_width = 0
    for character in word:
        character_width = max(wcwidth(character), 0)
        if current and current_width + character_width > line_length:
            chunks.append(current)
            current = ""
            current_width = 0
        current += character
        current_width += character_width
    if current:
        chunks.append(current)
    return chunks or [word]


def justify_line(words: list[str], line_length: int) -> str:
    """Distribute spacing across ``words`` so the line fills ``line_length``.

    Args:
        words: The words on the line.
        line_length: The target line width in display columns.

    Returns:
        The justified line.
    """
    from wcwidth import wcswidth

    if not words:
        return " " * line_length

    if len(words) == 1:
        # If there's only one word, left-justify it.
        return words[0].ljust(line_length)

    total_words_length = sum(wcswidth(word) for word in words)
    total_spaces = line_length - total_words_length
    if total_spaces < len(words) - 1:
        return " ".join(words).ljust(line_length)
    gaps = len(words) - 1
    spaces_between_words = [total_spaces // gaps] * gaps

    # Distribute the remaining spaces from left to right.
    for i in range(total_spaces % gaps):
        spaces_between_words[i] += 1

    line = ""
    for i, word in enumerate(words[:-1]):
        line += word + " " * spaces_between_words[i]
    line += words[-1]  # The last word has no trailing spaces.
    return line


class KneeboardSink:
    """Format a note, copy it to the clipboard, and paste it into the DCS kneeboard."""

    def __init__(self, line_length: Callable[[], int], reporter: StatusReporter) -> None:
        """Wire the line-length source and status reporter.

        Args:
            line_length: Callable returning the current kneeboard page width (read
                live so a config change takes effect without a restart).
            reporter: The user-facing status reporter port.
        """
        self._line_length = line_length
        self._reporter = reporter

    def send(self, note_text: str) -> None:
        """Format ``note_text`` and deliver it to the in-game kneeboard."""
        import pyperclip

        text_for_kneeboard = format_for_dcs_kneeboard(note_text, self._line_length())
        pyperclip.copy(text_for_kneeboard)
        _LOGGER.info("Text copied to clipboard for DCS kneeboard.")
        try:
            import keyboard

            keyboard.press_and_release(_KNEEBOARD_HOTKEY)
            self._reporter.report(f"Sent text to DCS: {text_for_kneeboard}", StatusLevel.SUCCESS)
            _LOGGER.info("DCS kneeboard populated")
        except Exception as error:
            _LOGGER.error("Failed to simulate keyboard shortcut: %s", error)
            self._reporter.report(
                f"Failed to simulate keyboard shortcut: {error}", StatusLevel.ERROR
            )
