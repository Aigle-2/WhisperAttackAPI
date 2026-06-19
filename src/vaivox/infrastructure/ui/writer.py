"""Tk status writer: the UI adapter behind the ``StatusReporter`` port.

It maps each :class:`~vaivox.application.ports.StatusLevel` to a themed colour tag
and writes to the app's scrolled text area. It also exposes ``write``/``write_dict``
for the startup context the UI prints directly. Tk constants are inlined as string
literals so the module imports without Tk installed (the widget is injected).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from vaivox.application.ports import StatusLevel
from vaivox.infrastructure.ui.theme import (
    TAG_BLACK,
    TAG_BLUE,
    TAG_GREEN,
    TAG_GREY,
    TAG_ORANGE,
    TAG_RED,
    theme_config,
)

if TYPE_CHECKING:
    from ttkbootstrap.scrolled import ScrolledText

# Tk widget state/index constants (string-valued; avoids importing tkinter here).
_STATE_NORMAL: Literal["normal"] = "normal"
_STATE_DISABLED: Literal["disabled"] = "disabled"
_INDEX_END: Literal["end"] = "end"

_LEVEL_TAGS: dict[StatusLevel, str] = {
    StatusLevel.INFO: TAG_BLACK,
    StatusLevel.DETAIL: TAG_GREY,
    StatusLevel.TRANSCRIPT: TAG_BLUE,
    StatusLevel.SUCCESS: TAG_GREEN,
    StatusLevel.WARNING: TAG_ORANGE,
    StatusLevel.ERROR: TAG_RED,
}


class TkStatusWriter:
    """Write status lines to the VAIVOX scrolled text area."""

    def __init__(
        self,
        theme: str,
        text_area: ScrolledText,
        on_status: Callable[[str, StatusLevel], None] | None = None,
    ) -> None:
        """Configure the colour tags for the active theme.

        Args:
            theme: The resolved theme name (``dark`` or ``light``).
            text_area: The scrolled text widget to write into.
            on_status: Optional callback for surfacing the latest semantic status in
                another widget such as the window header.
        """
        self.text_area = text_area
        self._on_status = on_status
        self._ui_thread_id = threading.get_ident()
        style = theme_config[theme]
        for tag in (TAG_BLACK, TAG_BLUE, TAG_GREEN, TAG_GREY, TAG_ORANGE, TAG_RED):
            self.text_area.tag_configure(tag, foreground=style[tag])

    def report(self, message: str, level: StatusLevel = StatusLevel.INFO) -> None:
        """Write ``message`` using the colour tag for ``level`` (StatusReporter port)."""
        self.write(message, _LEVEL_TAGS[level])
        if self._on_status is not None:
            self._on_status(message, level)

    def write(self, text: str, tag: str = TAG_BLACK) -> None:
        """Append a line to the text area, keeping it read-only outside the write."""
        if threading.get_ident() != self._ui_thread_id:
            self.text_area.after(0, self._write_on_ui_thread, text, tag)
            return
        self._write_on_ui_thread(text, tag)

    def _write_on_ui_thread(self, text: str, tag: str) -> None:
        """Append a line to the text area from the Tk thread."""
        self.text_area.text.configure(state=_STATE_NORMAL)
        self.text_area.insert(_INDEX_END, text + "\n", tag)
        self.text_area.see(_INDEX_END)
        self.text_area.text.configure(state=_STATE_DISABLED)

    def clear(self) -> None:
        """Clear the text area, keeping it read-only outside the operation."""
        if threading.get_ident() != self._ui_thread_id:
            self.text_area.after(0, self._clear_on_ui_thread)
            return
        self._clear_on_ui_thread()

    def _clear_on_ui_thread(self) -> None:
        """Clear the text area from the Tk thread."""
        self.text_area.text.configure(state=_STATE_NORMAL)
        self.text_area.delete("1.0", _INDEX_END)
        self.text_area.text.configure(state=_STATE_DISABLED)

    def write_dict(self, dictionary: dict[str, str], tag: str = TAG_BLACK) -> None:
        """Write each ``key: value`` pair of ``dictionary`` on its own line."""
        for key, value in dictionary.items():
            self.write(f"{key}: {value}", tag)
