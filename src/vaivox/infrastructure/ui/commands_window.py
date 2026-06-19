"""Window listing every speakable command, with live search (UI adapter).

The window shows the union of the permanent ("core") command phrases and the
mission-scoped F10 overlay — exactly the live phrase index the snapper matches against
(:class:`~vaivox.infrastructure.reload.phrase_snapper.ReloadablePhraseSnapper`). The list
is sorted alphabetically (case-insensitively) and filtered live from a search box: typing
narrows the list and selects the closest match, the arrow keys move the selection without
leaving the search box, and Enter moves focus into the list. Because the phrase index is
hot-reloaded when the VAICOM vocabulary regenerates or the mission F10 poll pulls new
commands (ADR-0005/0009), the window polls its source and re-renders when it changes, so an
open window stays current without a reopen.

ttkbootstrap and tkinter are imported lazily inside the constructor so the module imports
without the UI stack installed (matching the other ``infrastructure/ui`` adapters).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from vaivox.infrastructure.ui.theme import TAG_BLACK, TAG_BLUE

if TYPE_CHECKING:
    from ttkbootstrap import Window

#: How often (ms) the window re-reads its command source to pick up hot-reloads.
_POLL_INTERVAL_MS = 1000


def sort_commands(commands: Iterable[str]) -> list[str]:
    """Return the commands de-duplicated and sorted alphabetically ascending.

    Args:
        commands: The raw command phrases (any order, possibly with casing duplicates or
            blank entries).

    Returns:
        The non-blank phrases, de-duplicated case-insensitively (first casing wins) and
        sorted case-insensitively ascending.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for command in commands:
        text = command.strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return sorted(unique, key=str.lower)


def filter_commands(commands: Sequence[str], query: str) -> list[str]:
    """Return the commands containing ``query`` (case-insensitive substring match).

    Args:
        commands: The (already sorted) command phrases to filter.
        query: The search text; blank returns every command unchanged.

    Returns:
        The matching commands in their original order. A blank query matches everything.
    """
    needle = query.strip().lower()
    if not needle:
        return list(commands)
    return [command for command in commands if needle in command.lower()]


class VaivoxCommands:
    """A non-modal window listing every speakable command, with live search."""

    def __init__(
        self,
        root: Window,
        get_commands: Callable[[], Sequence[str]],
        palette: Mapping[str, str],
        on_close: Callable[[], None] | None = None,
    ) -> None:
        """Build and display the commands window.

        Args:
            root: The parent application window.
            get_commands: Returns the current speakable command phrases (the live phrase
                index: core + mission F10). Polled so the list tracks hot-reloads.
            palette: The active theme palette (used to colour the non-themed listbox).
            on_close: Optional callback invoked when the window is closed (so the app can
                drop its single-instance reference).
        """
        from tkinter import BOTH, END, LEFT, RIGHT, Listbox, Scrollbar, StringVar, X, Y, font

        from ttkbootstrap import Entry, Frame, Label, Toplevel

        self._get_commands = get_commands
        self._on_close = on_close
        self._all_commands: list[str] = []
        self._filtered: list[str] = []
        self._signature: tuple[str, ...] = ()
        self._after_id: str | None = None

        window_width = 560
        window_height = 640
        parent_x = root.winfo_x()
        parent_y = root.winfo_y()
        parent_width = root.winfo_width()
        parent_height = root.winfo_height()
        x = parent_x + (parent_width // 2) - (window_width // 2)
        y = parent_y + (parent_height // 2) - (window_height // 2)

        window = Toplevel(
            title="Available commands",
            size=(window_width, window_height),
            position=(x, y),
            transient=root,
        )
        self._window: Any = window

        custom_font = font.Font(family="GG Sans", size=11)
        self._query: Any = StringVar()

        search_frame = Frame(window)
        search_frame.pack(fill=X, padx=16, pady=(16, 6))
        Label(search_frame, text="Search").pack(side=LEFT, padx=(0, 8))
        entry = Entry(search_frame, textvariable=self._query, font=custom_font)
        entry.pack(side=LEFT, fill=X, expand=True)
        self._entry: Any = entry

        self._count: Any = StringVar(value="")
        Label(window, textvariable=self._count, bootstyle="secondary").pack(
            anchor="w", padx=16, pady=(0, 8)
        )

        list_frame = Frame(window)
        list_frame.pack(fill=BOTH, expand=True, padx=16, pady=(0, 16))
        scrollbar = Scrollbar(list_frame)
        scrollbar.pack(side=RIGHT, fill=Y)
        listbox = Listbox(
            list_frame,
            font=custom_font,
            activestyle="none",
            yscrollcommand=scrollbar.set,
            background=palette["text_background"],
            foreground=palette[TAG_BLACK],
            selectbackground=palette[TAG_BLUE],
            selectforeground=palette["text_background"],
            highlightthickness=0,
            borderwidth=0,
            exportselection=False,
        )
        listbox.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.configure(command=listbox.yview)
        self._listbox: Any = listbox
        self._end = END

        self._query.trace_add("write", self._on_query_changed)
        entry.bind("<Down>", self._select_next)
        entry.bind("<Up>", self._select_previous)
        entry.bind("<Return>", self._focus_list)
        listbox.bind("<Return>", self._copy_selection)
        listbox.bind("<Double-Button-1>", self._copy_selection)

        window.protocol("WM_DELETE_WINDOW", self._close)

        self._refresh_commands()
        entry.focus_set()
        self._after_id = window.after(_POLL_INTERVAL_MS, self._poll)

    def lift(self) -> None:
        """Bring an already-open window to the front and focus the search box."""
        self._window.deiconify()
        self._window.lift()
        self._window.focus_force()
        self._entry.focus_set()

    def _poll(self) -> None:
        """Re-read the command source and reschedule (live hot-reload tracking)."""
        self._refresh_commands()
        self._after_id = self._window.after(_POLL_INTERVAL_MS, self._poll)

    def _refresh_commands(self) -> None:
        """Reload + re-render only when the underlying command set changed."""
        commands = tuple(self._get_commands())
        if commands == self._signature:
            return
        self._signature = commands
        self._all_commands = sort_commands(commands)
        self._apply_filter(preserve=True)

    def _on_query_changed(self, *_args: object) -> None:
        """Re-filter the list when the search text changes."""
        self._apply_filter()

    def _apply_filter(self, preserve: bool = False) -> None:
        """Rebuild the listbox from the current search text.

        Args:
            preserve: Keep the currently selected command selected if it survives the
                filter (used on a background refresh so the user's place is not lost).
        """
        previous = self._selected_command() if preserve else None
        self._filtered = filter_commands(self._all_commands, self._query.get())
        self._listbox.delete(0, self._end)
        for command in self._filtered:
            self._listbox.insert(self._end, command)
        self._update_count()
        self._select_command(previous)

    def _update_count(self) -> None:
        """Refresh the "N commands" summary under the search box."""
        total = len(self._all_commands)
        shown = len(self._filtered)
        if total == 0:
            self._count.set("No commands yet — refresh the VAICOM vocabulary")
        elif shown == total:
            self._count.set(f"{total} commands")
        else:
            self._count.set(f"{shown} of {total} commands")

    def _select_command(self, command: str | None) -> None:
        """Select ``command`` if still present, else the first (closest) match."""
        if not self._filtered:
            return
        index = 0
        if command is not None:
            try:
                index = self._filtered.index(command)
            except ValueError:
                index = 0
        self._set_selection(index)

    def _set_selection(self, index: int) -> None:
        """Move the selection to ``index`` and scroll it into view."""
        self._listbox.selection_clear(0, self._end)
        self._listbox.selection_set(index)
        self._listbox.activate(index)
        self._listbox.see(index)

    def _selected_command(self) -> str | None:
        """Return the currently selected command phrase, or ``None``."""
        selection = self._listbox.curselection()
        if not selection:
            return None
        return self._filtered[int(selection[0])]

    def _move_selection(self, delta: int) -> None:
        """Shift the selection by ``delta`` rows, clamped to the list bounds."""
        if not self._filtered:
            return
        selection = self._listbox.curselection()
        if not selection:
            # No selection yet: Down lands on the first row, Up on the last.
            self._set_selection(0 if delta > 0 else len(self._filtered) - 1)
            return
        index = max(0, min(selection[0] + delta, len(self._filtered) - 1))
        self._set_selection(index)

    def _select_next(self, _event: object = None) -> str:
        """Move the selection down one row (bound to Down in the search box)."""
        self._move_selection(1)
        return "break"

    def _select_previous(self, _event: object = None) -> str:
        """Move the selection up one row (bound to Up in the search box)."""
        self._move_selection(-1)
        return "break"

    def _focus_list(self, _event: object = None) -> str:
        """Move keyboard focus into the list (bound to Enter in the search box)."""
        self._listbox.focus_set()
        if self._filtered and not self._listbox.curselection():
            self._set_selection(0)
        return "break"

    def _copy_selection(self, _event: object = None) -> str:
        """Copy the selected command to the clipboard (Enter / double-click in the list)."""
        command = self._selected_command()
        if command is not None:
            self._window.clipboard_clear()
            self._window.clipboard_append(command)
        return "break"

    def _close(self) -> None:
        """Cancel the poll timer, notify the owner, and destroy the window."""
        if self._after_id is not None:
            self._window.after_cancel(self._after_id)
            self._after_id = None
        if self._on_close is not None:
            self._on_close()
        self._window.destroy()
