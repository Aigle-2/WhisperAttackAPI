"""Window listing every speakable command, with live search (UI adapter).

The window is a two-tab notebook: a **Core** tab over the permanent command phrases and an
**F10** tab over the mission-scoped F10 overlay (each the live phrase set the snapper
matches against). Within a tab the list is sorted alphabetically (case-insensitively) and
filtered live from a search box: typing narrows the list and selects the closest match, the
arrow keys move the selection without leaving the search box, and Enter moves focus into the
list. A horizontal scrollbar keeps long bracketed command templates
(``[Radio] [Channel] [1..18]``) fully readable rather than clipping them at the edge.

Because the phrase sets are hot-reloaded when the VAICOM vocabulary regenerates or the
mission F10 poll pulls new commands (ADR-0005/0009), each tab polls its source and re-renders
when it changes, so an open window stays current without a reopen.

ttkbootstrap and tkinter are imported lazily inside the constructors so the module imports
without the UI stack installed (matching the other ``infrastructure/ui`` adapters).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from vaivox.infrastructure.ui.theme import TAG_BLACK, TAG_BLUE
from vaivox.infrastructure.vocabulary.command_catalog import (
    CommandCatalogEntry,
    entry_matches_aircraft,
)
from vaivox.infrastructure.voiceattack.dynamic_patterns import (
    format_voiceattack_pattern,
    voiceattack_pattern_matches,
)

if TYPE_CHECKING:
    from tkinter import Misc
    from tkinter.font import Font

    from ttkbootstrap import Window

#: How often (ms) each tab re-reads its command source to pick up hot-reloads.
_POLL_INTERVAL_MS = 1000
_SCOPE_FILTER_COLUMNS = 3

CommandSourceEntry = str | CommandCatalogEntry


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


def sort_command_entries(commands: Iterable[CommandSourceEntry]) -> list[CommandCatalogEntry]:
    """Return command entries de-duplicated and sorted by their display phrase."""
    entries: list[CommandCatalogEntry] = []
    for command in commands:
        if isinstance(command, CommandCatalogEntry):
            entries.append(command)
        else:
            entries.append(CommandCatalogEntry(command))
    phrases = sort_commands(entry.phrase for entry in entries)
    by_key: dict[str, CommandCatalogEntry] = {}
    for entry in entries:
        key = entry.phrase.strip().casefold()
        if not key:
            continue
        if key not in by_key:
            by_key[key] = entry
            continue
        previous = by_key[key]
        by_key[key] = CommandCatalogEntry(
            previous.phrase,
            groups=_unique_scope_values((*previous.groups, *entry.groups)),
            aircraft=_unique_scope_values((*previous.aircraft, *entry.aircraft)),
            sources=_unique_scope_values((*previous.sources, *entry.sources)),
        )
    return sorted(
        (by_key[phrase.casefold()] for phrase in phrases),
        key=lambda entry: display_command_entry(entry).lower(),
    )


def display_command_entry(command: CommandCatalogEntry) -> str:
    """Return the player-readable command text shown in the Commands window."""
    return format_voiceattack_pattern(command.phrase)


def aircraft_scope_options(
    commands: Iterable[CommandCatalogEntry],
    current_aircraft: str | None = None,
) -> tuple[str, ...]:
    """Return catalog aircraft tags with the current-aircraft match first."""
    tags = _unique_scope_values(tag for command in commands for tag in command.aircraft)
    return tuple(sorted(tags, key=lambda tag: _aircraft_scope_sort_key(tag, current_aircraft)))


def filter_command_entries(
    commands: Sequence[CommandCatalogEntry],
    query: str,
    *,
    current_aircraft: str | None = None,
    include_current: bool = True,
    include_general: bool = True,
    include_other: bool = True,
    included_aircraft: Sequence[str] = (),
    scope_filter_enabled: bool = False,
    include_profile: bool = True,
    include_keywords: bool = True,
    source_filter_enabled: bool = False,
) -> list[CommandCatalogEntry]:
    """Return command entries matching text plus optional aircraft/source filters."""
    needle = query.strip().lower()
    filtered: list[CommandCatalogEntry] = []
    for command in commands:
        if needle and not _entry_matches_query(command, query):
            continue
        if scope_filter_enabled and not _scope_included(
            command,
            current_aircraft=current_aircraft,
            include_current=include_current,
            include_general=include_general,
            include_other=include_other,
            included_aircraft=included_aircraft,
        ):
            continue
        if source_filter_enabled and not _source_included(
            command,
            include_profile=include_profile,
            include_keywords=include_keywords,
        ):
            continue
        filtered.append(command)
    return filtered


def _entry_matches_query(command: CommandCatalogEntry, query: str) -> bool:
    needle = query.strip().lower()
    if not needle:
        return True
    raw = command.phrase.lower()
    display = display_command_entry(command).lower()
    return needle in raw or needle in display or voiceattack_pattern_matches(command.phrase, query)


def _scope_included(
    command: CommandCatalogEntry,
    *,
    current_aircraft: str | None,
    include_current: bool,
    include_general: bool,
    include_other: bool,
    included_aircraft: Sequence[str],
) -> bool:
    if not command.aircraft:
        return include_general
    matches_current = entry_matches_aircraft(command, current_aircraft)
    if include_current and matches_current:
        return True
    if any(entry_matches_aircraft(command, aircraft) for aircraft in included_aircraft):
        return True
    return include_other and not matches_current


def _aircraft_scope_sort_key(tag: str, current_aircraft: str | None) -> tuple[int, str]:
    current_rank = 0 if _aircraft_tag_matches(tag, current_aircraft) else 1
    return (current_rank, tag.casefold())


def _aircraft_tag_matches(tag: str, current_aircraft: str | None) -> bool:
    return entry_matches_aircraft(CommandCatalogEntry(tag, aircraft=(tag,)), current_aircraft)


def _source_included(
    command: CommandCatalogEntry,
    *,
    include_profile: bool,
    include_keywords: bool,
) -> bool:
    return (include_profile and _is_profile_command_source(command)) or (
        include_keywords and _is_keyword_command_source(command)
    )


def _is_profile_command_source(command: CommandCatalogEntry) -> bool:
    return not command.sources or any(
        source.casefold().endswith(".vap") for source in command.sources
    )


def _is_keyword_command_source(command: CommandCatalogEntry) -> bool:
    keyword_sources = {"keywords.txt", "keywords.html"}
    return any(source.casefold() in keyword_sources for source in command.sources)


def _unique_scope_values(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return tuple(unique)


class _CommandsTab:
    """One notebook tab: a live-searchable, alphabetically-sorted command list."""

    def __init__(
        self,
        parent: Misc,
        get_commands: Callable[[], Sequence[CommandSourceEntry]],
        palette: Mapping[str, str],
        custom_font: Font,
        empty_message: str,
        *,
        get_current_aircraft: Callable[[], str | None] | None = None,
        enable_scope_filters: bool = False,
        enable_source_filters: bool = False,
    ) -> None:
        """Build the search box, count label, and scrolled listbox into ``parent``.

        Args:
            parent: The notebook page frame to populate.
            get_commands: Returns this tab's current command phrases (polled live).
            palette: The active theme palette (used to colour the non-themed listbox).
            custom_font: The shared UI font.
            empty_message: The count-label text shown when the source is empty.
            get_current_aircraft: Returns the current DCS aircraft/module name, when known.
            enable_scope_filters: Whether this tab should show aircraft-scope filters.
            enable_source_filters: Whether this tab should show profile/keyword filters.
        """
        from tkinter import (
            BOTH,
            END,
            EW,
            HORIZONTAL,
            LEFT,
            NS,
            NSEW,
            VERTICAL,
            BooleanVar,
            Listbox,
            Scrollbar,
            StringVar,
            X,
        )

        from ttkbootstrap import Checkbutton, Entry, Frame, Label

        self._get_commands = get_commands
        self._get_current_aircraft = get_current_aircraft or (lambda: None)
        self._empty_message = empty_message
        self._enable_scope_filters = enable_scope_filters
        self._enable_source_filters = enable_source_filters
        self._scope_filter_active = False
        self._source_filter_active = False
        self._current_aircraft: str | None = None
        self._all_commands: list[CommandCatalogEntry] = []
        self._filtered: list[CommandCatalogEntry] = []
        self._scope_total = 0
        self._signature: tuple[CommandSourceEntry, ...] = ()
        self._end = END

        self._query: Any = StringVar()
        self._include_current: Any = BooleanVar(value=True)
        self._include_general: Any = BooleanVar(value=False)
        self._aircraft_filter_vars: dict[str, Any] = {}
        self._aircraft_filter_widgets: dict[str, Any] = {}
        self._include_profile: Any = BooleanVar(value=True)
        self._include_keywords: Any = BooleanVar(value=True)
        search_frame = Frame(parent)
        search_frame.pack(fill=X, padx=12, pady=(12, 6))
        Label(search_frame, text="Search").pack(side=LEFT, padx=(0, 8))
        entry = Entry(search_frame, textvariable=self._query, font=custom_font)
        entry.pack(side=LEFT, fill=X, expand=True)
        self._entry: Any = entry

        self._scope_widgets: list[Any] = []
        self._scope_frame: Any | None = None
        self._current_scope_check: Any | None = None
        self._general_scope_check: Any | None = None
        if enable_scope_filters:
            scope_frame = Frame(parent)
            scope_frame.pack(fill=X, padx=12, pady=(0, 6))
            self._scope_frame = scope_frame
            current_check = Checkbutton(
                scope_frame,
                text="Current aircraft",
                variable=self._include_current,
                command=self._on_scope_filter_changed,
            )
            self._current_scope_check = current_check
            self._scope_widgets.append(current_check)
            general_check = Checkbutton(
                scope_frame,
                text="General",
                variable=self._include_general,
                command=self._on_scope_filter_changed,
            )
            self._general_scope_check = general_check
            self._scope_widgets.append(general_check)
            self._layout_scope_widgets()

        self._source_widgets: list[Any] = []
        if enable_source_filters:
            source_frame = Frame(parent)
            source_frame.pack(fill=X, padx=12, pady=(0, 6))
            for label, variable in (
                ("Profile commands", self._include_profile),
                ("VAICOM keyword actions", self._include_keywords),
            ):
                widget = Checkbutton(
                    source_frame,
                    text=label,
                    variable=variable,
                    command=self._on_source_filter_changed,
                )
                widget.pack(side=LEFT, padx=(0, 12))
                self._source_widgets.append(widget)

        self._count: Any = StringVar(value="")
        Label(parent, textvariable=self._count, bootstyle="secondary").pack(
            anchor="w", padx=12, pady=(0, 6)
        )

        list_frame = Frame(parent)
        list_frame.pack(fill=BOTH, expand=True, padx=12, pady=(0, 12))
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        yscroll = Scrollbar(list_frame, orient=VERTICAL)
        xscroll = Scrollbar(list_frame, orient=HORIZONTAL)
        listbox = Listbox(
            list_frame,
            font=custom_font,
            activestyle="none",
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set,
            background=palette["text_background"],
            foreground=palette[TAG_BLACK],
            selectbackground=palette[TAG_BLUE],
            selectforeground=palette["text_background"],
            highlightthickness=0,
            borderwidth=0,
            exportselection=False,
        )
        listbox.grid(row=0, column=0, sticky=NSEW)
        yscroll.grid(row=0, column=1, sticky=NS)
        xscroll.grid(row=1, column=0, sticky=EW)
        yscroll.configure(command=listbox.yview)
        xscroll.configure(command=listbox.xview)
        self._listbox: Any = listbox

        self._query.trace_add("write", self._on_query_changed)
        entry.bind("<Down>", self._select_next)
        entry.bind("<Up>", self._select_previous)
        entry.bind("<Return>", self._focus_list)
        listbox.bind("<Return>", self._copy_selection)
        listbox.bind("<Double-Button-1>", self._copy_selection)

        self.refresh()

    def focus_search(self) -> None:
        """Move keyboard focus to this tab's search box."""
        self._entry.focus_set()

    def refresh(self) -> None:
        """Reload + re-render only when this tab's command set changed."""
        commands = tuple(self._get_commands())
        current_aircraft = self._get_current_aircraft()
        if commands == self._signature and current_aircraft == self._current_aircraft:
            return
        if commands != self._signature:
            self._signature = commands
            self._all_commands = sort_command_entries(commands)
        self._current_aircraft = current_aircraft
        self._update_scope_filters()
        self._update_source_filters()
        self._apply_filter(preserve=True)

    def _on_query_changed(self, *_args: object) -> None:
        """Re-filter the list when the search text changes."""
        self._apply_filter()

    def _on_scope_filter_changed(self) -> None:
        """Re-filter the list when a scope checkbox changes."""
        self._apply_filter()

    def _on_source_filter_changed(self) -> None:
        """Re-filter the list when a source checkbox changes."""
        self._apply_filter()

    def _apply_filter(self, preserve: bool = False) -> None:
        """Rebuild the listbox from the current search text.

        Args:
            preserve: Keep the currently selected command selected if it survives the
                filter (used on a background refresh so the user's place is not lost).
        """
        previous = self._selected_command() if preserve else None
        self._scope_total = len(
            filter_command_entries(
                self._all_commands,
                "",
                current_aircraft=self._current_aircraft,
                include_current=bool(self._include_current.get()),
                include_general=bool(self._include_general.get()),
                include_other=False,
                included_aircraft=self._selected_aircraft_filters(),
                scope_filter_enabled=self._scope_filter_active,
                include_profile=bool(self._include_profile.get()),
                include_keywords=bool(self._include_keywords.get()),
                source_filter_enabled=self._source_filter_active,
            )
        )
        self._filtered = filter_command_entries(
            self._all_commands,
            self._query.get(),
            current_aircraft=self._current_aircraft,
            include_current=bool(self._include_current.get()),
            include_general=bool(self._include_general.get()),
            include_other=False,
            included_aircraft=self._selected_aircraft_filters(),
            scope_filter_enabled=self._scope_filter_active,
            include_profile=bool(self._include_profile.get()),
            include_keywords=bool(self._include_keywords.get()),
            source_filter_enabled=self._source_filter_active,
        )
        self._listbox.delete(0, self._end)
        for command in self._filtered:
            self._listbox.insert(self._end, display_command_entry(command))
        self._update_count()
        self._select_command(previous)

    def _update_scope_filters(self) -> None:
        """Enable scope checkboxes only when catalog metadata and an aircraft are known."""
        has_scoped_entries = any(command.aircraft for command in self._all_commands)
        self._scope_filter_active = bool(
            self._enable_scope_filters and has_scoped_entries and self._current_aircraft
        )
        self._sync_aircraft_scope_widgets()
        if not self._scope_widgets:
            return
        state = "normal" if self._scope_filter_active else "disabled"
        if self._current_scope_check is not None:
            label = (
                f"{self._current_aircraft} only"
                if self._scope_filter_active
                else "Current aircraft"
            )
            self._current_scope_check.configure(text=label)
        for widget in self._scope_widgets:
            widget.configure(state=state)

    def _sync_aircraft_scope_widgets(self) -> None:
        """Rebuild the dynamic aircraft checkboxes from catalog aircraft tags."""
        from tkinter import BooleanVar

        from ttkbootstrap import Checkbutton

        if self._scope_frame is None:
            return
        options = tuple(
            tag
            for tag in aircraft_scope_options(self._all_commands, self._current_aircraft)
            if not _aircraft_tag_matches(tag, self._current_aircraft)
        )
        for tag in tuple(self._aircraft_filter_widgets):
            if tag in options:
                continue
            self._aircraft_filter_widgets.pop(tag).destroy()
            self._aircraft_filter_vars.pop(tag, None)
        for tag in options:
            if tag in self._aircraft_filter_widgets:
                continue
            variable = BooleanVar(value=False)
            widget = Checkbutton(
                self._scope_frame,
                text=tag,
                variable=variable,
                command=self._on_scope_filter_changed,
            )
            self._aircraft_filter_vars[tag] = variable
            self._aircraft_filter_widgets[tag] = widget
        self._scope_widgets = [
            widget
            for widget in (self._current_scope_check, self._general_scope_check)
            if widget is not None
        ]
        self._scope_widgets.extend(self._aircraft_filter_widgets[tag] for tag in options)
        self._layout_scope_widgets()

    def _layout_scope_widgets(self) -> None:
        """Place scope filters in stable rows so many aircraft tags do not overflow."""
        for index, widget in enumerate(self._scope_widgets):
            widget.grid_forget()
            widget.grid(
                row=index // _SCOPE_FILTER_COLUMNS,
                column=index % _SCOPE_FILTER_COLUMNS,
                sticky="w",
                padx=(0, 12),
                pady=(0, 4),
            )

    def _selected_aircraft_filters(self) -> tuple[str, ...]:
        """Return the dynamic aircraft tags currently checked by the user."""
        return tuple(
            tag for tag, variable in self._aircraft_filter_vars.items() if bool(variable.get())
        )

    def _update_source_filters(self) -> None:
        """Enable source checkboxes only when catalog source metadata is present."""
        self._source_filter_active = bool(
            self._enable_source_filters and any(command.sources for command in self._all_commands)
        )
        if not self._source_widgets:
            return
        state = "normal" if self._source_filter_active else "disabled"
        for widget in self._source_widgets:
            widget.configure(state=state)

    def _update_count(self) -> None:
        """Refresh the "N commands" summary under the search box."""
        source_total = len(self._all_commands)
        total = self._scope_total if self._scope_filter_active else source_total
        shown = len(self._filtered)
        if source_total == 0:
            self._count.set(self._empty_message)
        elif total == 0:
            self._count.set("0 commands")
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
            for candidate_index, candidate in enumerate(self._filtered):
                if candidate.phrase == command:
                    index = candidate_index
                    break
        self._set_selection(index)

    def _set_selection(self, index: int) -> None:
        """Move the selection to ``index`` and scroll it into view."""
        self._listbox.selection_clear(0, self._end)
        self._listbox.selection_set(index)
        self._listbox.activate(index)
        self._listbox.see(index)

    def _selected_command(self) -> str | None:
        """Return the currently selected command phrase, or ``None``."""
        entry = self._selected_entry()
        return None if entry is None else entry.phrase

    def _selected_entry(self) -> CommandCatalogEntry | None:
        """Return the currently selected command entry, or ``None``."""
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
        command = self._selected_entry()
        if command is not None:
            self._listbox.clipboard_clear()
            self._listbox.clipboard_append(display_command_entry(command))
        return "break"


class VaivoxCommands:
    """A non-modal window with Core / F10 tabs listing every speakable command."""

    def __init__(
        self,
        root: Window,
        get_core_commands: Callable[[], Sequence[CommandSourceEntry]],
        get_mission_commands: Callable[[], Sequence[str]],
        get_current_aircraft: Callable[[], str | None] | None,
        palette: Mapping[str, str],
        on_close: Callable[[], None] | None = None,
    ) -> None:
        """Build and display the commands window.

        Args:
            root: The parent application window.
            get_core_commands: Returns the live permanent command phrases (Core tab).
            get_mission_commands: Returns the live mission F10 command phrases (F10 tab).
            get_current_aircraft: Returns the current DCS aircraft/module name, when known.
            palette: The active theme palette (used to colour the non-themed listboxes).
            on_close: Optional callback invoked when the window is closed (so the app can
                drop its single-instance reference).
        """
        from tkinter import BOTH, font

        from ttkbootstrap import Frame, Notebook, Toplevel

        self._on_close = on_close
        self._after_id: str | None = None

        window_width = 620
        window_height = 680
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
        notebook = Notebook(window)
        notebook.pack(fill=BOTH, expand=True, padx=12, pady=12)

        self._tabs: list[_CommandsTab] = []
        specs: list[tuple[str, Callable[[], Sequence[CommandSourceEntry]], str]] = [
            ("Core", get_core_commands, "No core commands yet — refresh the VAICOM vocabulary"),
            ("F10", get_mission_commands, "No F10 commands pulled this session"),
        ]
        scope_filters = {"Core": True}
        source_filters = {"Core": True}
        for label, get_commands, empty_message in specs:
            page = Frame(notebook)
            notebook.add(page, text=label)
            self._tabs.append(
                _CommandsTab(
                    page,
                    get_commands,
                    palette,
                    custom_font,
                    empty_message,
                    get_current_aircraft=get_current_aircraft,
                    enable_scope_filters=scope_filters.get(label, False),
                    enable_source_filters=source_filters.get(label, False),
                )
            )

        window.protocol("WM_DELETE_WINDOW", self._close)
        if self._tabs:
            self._tabs[0].focus_search()
        self._after_id = window.after(_POLL_INTERVAL_MS, self._poll)

    def lift(self) -> None:
        """Bring an already-open window to the front and focus the first tab's search box."""
        self._window.deiconify()
        self._window.lift()
        self._window.focus_force()
        if self._tabs:
            self._tabs[0].focus_search()

    def _poll(self) -> None:
        """Re-read every tab's source and reschedule (live hot-reload tracking)."""
        for tab in self._tabs:
            tab.refresh()
        self._after_id = self._window.after(_POLL_INTERVAL_MS, self._poll)

    def _close(self) -> None:
        """Cancel the poll timer, notify the owner, and destroy the window."""
        if self._after_id is not None:
            self._window.after_cancel(self._after_id)
            self._after_id = None
        if self._on_close is not None:
            self._on_close()
        self._window.destroy()
