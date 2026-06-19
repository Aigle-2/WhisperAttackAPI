"""Windowed application + system-tray adapter (the driver UI).

This is the ttkbootstrap window and pystray tray relocated from the legacy
``whisper_attack`` god-module. It owns the widgets, prints the startup context, and
runs the control server (built by the composition root) on the tray thread. All UI
libraries are imported lazily so the module imports without them installed.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import traceback
from os import path
from threading import Event
from typing import TYPE_CHECKING, Any, cast

from vaivox import composition
from vaivox.application.ports import StatusLevel
from vaivox.domain.reconciliation.snapper import DEFAULT_HIGH
from vaivox.infrastructure.config.identity import VAIVOX
from vaivox.infrastructure.config.settings import VaivoxConfiguration
from vaivox.infrastructure.ui.commands_window import VaivoxCommands
from vaivox.infrastructure.ui.settings import VaivoxSettings
from vaivox.infrastructure.ui.theme import (
    TAG_BLACK,
    TAG_BLUE,
    TAG_GREY,
    TAG_RED,
    THEME_DARK,
    THEME_DEFAULT,
    theme_config,
)
from vaivox.infrastructure.ui.word_mappings import VaivoxWordMappings
from vaivox.infrastructure.ui.writer import TkStatusWriter

if TYPE_CHECKING:
    from tkinter.font import Font

    from ttkbootstrap import Style

    from vaivox.application.refresh_vocabulary import MissionVocabularyRefreshResult
    from vaivox.domain.vocabulary.keyterms import KeytermBudget

_LOGGER = logging.getLogger(__name__)

_SUPPORTED_KEYTERM_PROVIDERS = {"elevenlabs", "deepgram", "openai"}


class VaivoxApp:
    """The VAIVOX window, system-tray icon, and control-server thread."""

    def __init__(self, app_path: str, app_data_dir: str) -> None:
        """Build the window, wire the control server, and start the tray thread.

        Args:
            app_path: Directory holding the bundled assets and default config.
            app_data_dir: The per-user data directory for overrides and logs.
        """
        from tkinter import DISABLED, LEFT, NSEW, WORD, PhotoImage, StringVar, W, font

        from PIL import Image
        from pystray import Icon, Menu, MenuItem
        from ttkbootstrap import Button, Frame, Label, Style, Window
        from ttkbootstrap.widgets.scrolled import ScrolledText

        _LOGGER.info("%s version: %s", VAIVOX.name, VAIVOX.version)
        _LOGGER.info("%s location: %s", VAIVOX.name, app_path)

        self.app_path = app_path
        self.app_data_dir = app_data_dir
        self.exit_event = Event()
        self._vocabulary_refresh_lock = threading.Lock()
        self._commands_window: VaivoxCommands | None = None

        self.window = Window(
            title=VAIVOX.window_title,
            iconphoto=path.join(app_path, "vaivox_icon.png"),
        )
        self.config = VaivoxConfiguration(app_path, app_data_dir)

        theme = self.get_theme()
        cast(Any, self.window.style).theme_use("darkly" if theme == THEME_DARK else "flatly")
        palette = theme_config[theme]
        self.palette = palette

        custom_font = font.Font(family="GG Sans", size=11)
        style = Style()  # type: ignore[no-untyped-call]
        self._configure_window_styles(style, custom_font, palette)
        self.window.configure(background=palette["background"])
        self.window.minsize(940, 620)

        self.app_icon: Any = PhotoImage(file=path.join(app_path, "vaivox_icon.png"))
        self.add_icon: Any = PhotoImage(file=path.join(app_path, "add_icon.png"))
        self.status_text: Any = StringVar(value="Starting services...")

        shell = Frame(self.window, style="App.TFrame")
        shell.grid(row=0, column=0, sticky=NSEW, padx=14, pady=14)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(2, weight=1)

        header = Frame(shell, style="Header.TFrame", padding=14)
        header.grid(row=0, column=0, sticky=NSEW)
        header.grid_columnconfigure(1, weight=1)
        Label(header, image=self.app_icon, style="Header.TLabel").grid(
            row=0,
            column=0,
            rowspan=2,
            sticky=W,
            padx=(0, 14),
        )
        Label(header, text=VAIVOX.name, style="Title.TLabel").grid(row=0, column=1, sticky=W)
        Label(
            header,
            text=f"VoiceAttack bridge | v{VAIVOX.version}",
            style="MutedHeader.TLabel",
        ).grid(row=1, column=1, sticky=W)
        Label(
            header,
            textvariable=self.status_text,
            style="Status.TLabel",
            anchor="e",
            justify="right",
            wraplength=400,
        ).grid(row=0, column=2, rowspan=2, sticky="e", padx=(16, 0))

        toolbar = Frame(shell, style="Toolbar.TFrame")
        toolbar.grid(row=1, column=0, sticky=NSEW, pady=(10, 8))
        toolbar.grid_columnconfigure(6, weight=1)

        add_word_mapping_button = Button(
            toolbar,
            text="Add mapping",
            style="secondary.TButton",
            image=self.add_icon,
            compound=LEFT,
            command=self.add_word_mapping,
        )
        add_word_mapping_button.grid(row=0, column=0, sticky=W, padx=(0, 8))
        self.refresh_button: Any = Button(
            toolbar,
            text="Refresh VAICOM vocabulary",
            style="primary.TButton",
            command=self.refresh_vocabulary_from_ui,
        )
        self.refresh_button.grid(row=0, column=1, sticky=W, padx=(0, 8))
        Button(
            toolbar,
            text="Commands",
            style="secondary.TButton",
            command=self.open_commands,
        ).grid(row=0, column=2, sticky=W, padx=(0, 8))
        Button(
            toolbar,
            text="Clear log",
            style="secondary.TButton",
            command=self.clear_log,
        ).grid(row=0, column=3, sticky=W, padx=(0, 8))
        Button(
            toolbar,
            text="Settings",
            style="secondary.TButton",
            command=self.open_settings,
        ).grid(row=0, column=4, sticky=W, padx=(0, 8))
        Button(
            toolbar,
            text="Open data folder",
            style="secondary.TButton",
            command=self.open_data_folder,
        ).grid(row=0, column=5, sticky=W)
        api_state = "on" if self.config.get_bool_setting("api_enabled", False) else "off"
        telemetry_state = "on" if self.config.get_bool_setting("telemetry_enabled", True) else "off"
        Label(
            toolbar,
            text=(
                f"STT: {self.config.get_stt_backend()}   |   "
                f"API: {api_state}   |   Telemetry: {telemetry_state}"
            ),
            style="ToolbarMeta.TLabel",
            anchor="e",
        ).grid(row=0, column=6, sticky="e", padx=(16, 0))

        text_area = ScrolledText(
            shell,
            wrap=WORD,
            width=104,
            height=34,
            state=DISABLED,
            autohide=True,
            font=custom_font,
        )
        text_area.grid(row=2, column=0, sticky=NSEW)
        text_area.text.configure(
            background=palette["text_background"],
            foreground=palette[TAG_BLACK],
            insertbackground=palette[TAG_BLACK],
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=10,
            selectbackground=palette[TAG_BLUE],
        )

        self.window.grid_rowconfigure(0, weight=1)
        self.window.grid_columnconfigure(0, weight=1)

        self.writer = TkStatusWriter(theme, text_area, on_status=self._set_status_from_report)
        self.writer.write("Loaded configuration:", TAG_BLUE)
        self.writer.write_dict(dict(self.config.get_safe_configuration()), TAG_GREY)

        wired = composition.build(
            config=self.config,
            reporter=self.writer,
            exit_event=self.exit_event,
            request_shutdown=self._close,
        )
        self.control_server = wired.control_server
        self.api_server = wired.api_server
        self.phrase_snapper = wired.phrase_snapper
        self.refresh_vocabulary = wired.refresh_vocabulary
        self.refresh_mission_vocabulary = wired.refresh_mission_vocabulary
        self.get_core_phrases = wired.get_core_phrases
        self.get_mission_phrases = wired.get_mission_phrases
        self.reconciliation_vocabulary = wired.reconciliation_vocabulary
        self.stt_keyterms = wired.stt_keyterms
        self.add_word_mapping_use_case = wired.add_word_mapping
        self.write_startup_context()
        if self.api_server is not None:
            self.api_server.start()

        image = Image.open(path.join(app_path, "vaivox_icon.png"))
        self.icon = Icon(
            VAIVOX.name,
            image,
            VAIVOX.name,
            menu=Menu(MenuItem("Show", self._show_window), MenuItem("Exit", self._close)),
        )
        self.window.protocol("WM_DELETE_WINDOW", self._withdraw_window)

        threading.excepthook = self._handle_exception
        threading.Thread(daemon=True, target=lambda: self.icon.run(setup=self._startup)).start()

        # Generate/refresh the VAICOM vocabulary off the UI thread (ADR-0005). It is a
        # no-op when up to date, falls back to the seed when no install is found, and
        # hot-applies a regenerated phrase index at idle (ADR-0009) — never blocking start.
        threading.Thread(daemon=True, target=self._refresh_vocabulary_in_background).start()
        if self.config.get_bool_setting("mission_f10_poll_enabled", True):
            threading.Thread(
                daemon=True,
                target=self._poll_mission_vocabulary_in_background,
            ).start()

    def run(self) -> None:
        """Run the Tk main loop (blocks until the window is destroyed)."""
        self.window.mainloop()

    def _refresh_vocabulary_in_background(self) -> None:
        """Run the VAICOM vocabulary refresh use case, guarding the background thread."""
        if not self._vocabulary_refresh_lock.acquire(blocking=False):
            return
        try:
            self.refresh_vocabulary.execute()
        except Exception:
            # The use case reports user-facing status itself; this guard only keeps an
            # unexpected failure from killing the daemon thread (ADR-0005 is best-effort).
            _LOGGER.exception("Background vocabulary refresh failed.")
        finally:
            self._vocabulary_refresh_lock.release()

    def _poll_mission_vocabulary_in_background(self) -> None:
        """Poll VAICOM's live F10 menu imports and hot-apply the mission overlay."""
        interval = self.config.get_int_setting(
            "mission_f10_poll_interval_seconds",
            15,
            min_value=5,
            max_value=3600,
        )
        first = True
        while not self.exit_event.is_set():
            try:
                result = self.refresh_mission_vocabulary.execute()
                if first:
                    first = False
                    self._report_mission_f10_source(result)
            except Exception:
                _LOGGER.exception("Mission F10 vocabulary refresh failed.")
            if self.exit_event.wait(interval):
                break

    def _report_mission_f10_source(self, result: MissionVocabularyRefreshResult) -> None:
        """Write a one-time diagnostic of where the F10 overlay is read from and what it found."""
        source = result.source or "no VAICOM log found"
        self.writer.write(
            f"Mission F10 source: {source} — {result.mission_phrases} commands ({result.reason})",
            TAG_GREY,
        )

    def _configure_window_styles(
        self,
        style: Style,
        custom_font: Font,
        palette: dict[str, str],
    ) -> None:
        """Configure ttk styles used by the VAIVOX window."""
        family = custom_font.actual("family")
        style.configure("TButton", font=custom_font)
        style.configure("TLabel", font=custom_font)
        style.configure("App.TFrame", background=palette["background"])
        style.configure("Header.TFrame", background=palette["surface"])
        style.configure(
            "Header.TLabel",
            background=palette["surface"],
            foreground=palette[TAG_BLACK],
            font=custom_font,
        )
        style.configure(
            "Title.TLabel",
            background=palette["surface"],
            foreground=palette[TAG_BLACK],
            font=(family, 18, "bold"),
        )
        style.configure(
            "MutedHeader.TLabel",
            background=palette["surface"],
            foreground=palette["muted"],
            font=(family, 10),
        )
        style.configure(
            "Status.TLabel",
            background=palette["surface"],
            foreground=palette[TAG_BLUE],
            font=(family, 10, "bold"),
        )
        style.configure("Toolbar.TFrame", background=palette["background"])
        style.configure(
            "ToolbarMeta.TLabel",
            background=palette["background"],
            foreground=palette["muted"],
            font=(family, 10),
        )

    def write_startup_context(self) -> None:
        """Write the startup vocabulary summary to the UI."""
        word_mappings = self.reconciliation_vocabulary.get_word_mappings()
        fuzzy_words = self.reconciliation_vocabulary.get_fuzzy_words()

        self.writer.write("Loaded post-processing word mappings:", TAG_BLUE)
        self.writer.write(f"{len(word_mappings)} mappings", TAG_GREY)
        self.writer.write_dict(dict(word_mappings), TAG_GREY)

        self.writer.write("Loaded fuzzy correction words:", TAG_BLUE)
        self.writer.write(f"{len(fuzzy_words)} words: {', '.join(fuzzy_words)}", TAG_GREY)
        if self.config.get_bool_setting("telemetry_enabled", True):
            self.writer.write(
                "Telemetry enabled: utterances are stored locally in telemetry.jsonl",
                TAG_GREY,
            )
        else:
            self.writer.write("Telemetry disabled", TAG_GREY)

        self.write_stt_keyterm_context()

    def write_stt_keyterm_context(self) -> None:
        """Write the effective STT keyterm context without dumping the whole list."""
        provider = self.config.get_stt_backend()
        source_counts = self.stt_keyterms.get_stt_keyterm_source_counts()
        all_keyterms = self.stt_keyterms.get_stt_keyterms()
        budget = self.stt_keyterms.get_provider_stt_keyterm_budget(provider)
        budgeted = self.stt_keyterms.get_provider_budgeted_stt_keyterm_details(
            provider, log_result=False
        )

        source_summary = (
            ", ".join(f"{source}={count}" for source, count in source_counts.items()) or "none"
        )
        limit_summary = self.format_keyterm_budget(budget)

        self.writer.write("Loaded STT keyterm context:", TAG_BLUE)
        self.writer.write(f"provider: {provider}", TAG_GREY)
        self.writer.write(f"sources: {source_summary}", TAG_GREY)
        self.writer.write(f"available: {len(all_keyterms)} unique terms", TAG_GREY)

        if provider not in _SUPPORTED_KEYTERM_PROVIDERS:
            self.writer.write(f"effective: not used by {provider}", TAG_GREY)
            return
        if provider == "openai" and not self.config.get_provider_bool(
            "openai", "include_keyterms_in_prompt", True
        ):
            self.writer.write("effective: disabled by openai_include_keyterms_in_prompt", TAG_GREY)
            return

        target = "OpenAI prompt" if provider == "openai" else provider
        self.writer.write(f"effective: {len(budgeted.keyterms)} terms sent to {target}", TAG_GREY)
        if limit_summary:
            self.writer.write(f"limits: {limit_summary}", TAG_GREY)
        if (
            budgeted.skipped_too_long
            or budgeted.omitted_by_term_limit
            or budgeted.omitted_by_char_limit
        ):
            self.writer.write(
                "omitted by budget: "
                f"too_long={budgeted.skipped_too_long}, "
                f"term_limit={budgeted.omitted_by_term_limit}, "
                f"char_limit={budgeted.omitted_by_char_limit}",
                TAG_GREY,
            )
        preview = ", ".join(budgeted.keyterms[:25])
        if preview:
            self.writer.write(f"preview: {preview}", TAG_GREY)

    def format_keyterm_budget(self, budget: KeytermBudget) -> str:
        """Render a provider keyterm budget as a compact ``key=value`` summary."""
        limits: list[str] = []
        if budget.max_terms is not None:
            limits.append(f"max_terms={budget.max_terms}")
        if budget.max_term_chars is not None:
            limits.append(f"max_term_chars={budget.max_term_chars}")
        if budget.max_total_chars is not None:
            limits.append(f"max_total_chars={budget.max_total_chars}")
        return ", ".join(limits)

    def add_word_mapping(self) -> None:
        """Open the modal dialog to add word mappings."""

        def update_word_mapping(aliases: str, replacement: str) -> None:
            try:
                entry = self.add_word_mapping_use_case.execute(aliases, replacement)
                if entry is None:
                    return
                self.writer.write("Added new word mapping:", TAG_BLUE)
                self.writer.write(f"{aliases}: {replacement}", TAG_GREY)
            except Exception as error:
                _LOGGER.exception("Failed to add word mapping.")
                self.writer.write(str(error), TAG_RED)

        VaivoxWordMappings(self.window, update_word_mapping)

    def open_commands(self) -> None:
        """Open (or re-focus) the window listing every speakable command.

        The window has a Core tab (permanent vocabulary) and an F10 tab (the mission
        overlay), each polling its live source so it tracks hot-reloads from a vocabulary
        refresh or a mission poll. Only one instance is kept open at a time.
        """
        if self._commands_window is not None:
            self._commands_window.lift()
            return
        self._commands_window = VaivoxCommands(
            self.window,
            get_core_commands=self.get_core_phrases,
            get_mission_commands=self.get_mission_phrases,
            palette=self.palette,
            on_close=self._on_commands_closed,
        )

    def _on_commands_closed(self) -> None:
        """Drop the single-instance reference once the commands window is closed."""
        self._commands_window = None

    def open_settings(self) -> None:
        """Open the runtime settings modal."""
        required_score = self.config.get_float_setting(
            "snap_high", DEFAULT_HIGH, min_value=0.0, max_value=100.0
        )
        verbose_f10 = self.config.get_bool_setting("mission_f10_verbose_logging", False)
        VaivoxSettings(self.window, required_score, verbose_f10, self.save_settings)

    def save_settings(self, required_score: float, verbose_f10_logging: bool) -> bool:
        """Persist and apply the settings modal (snap score + verbose F10 pull logging).

        The verbose flag is read live by the mission F10 poll, so it takes effect on the
        next poll without a restart; the snap score is hot-applied through the snapper.
        """
        value = f"{required_score:.1f}"
        try:
            self.config.set_custom_settings(
                {
                    "snap_high": value,
                    "mission_f10_verbose_logging": "true" if verbose_f10_logging else "false",
                }
            )
            applied = self.phrase_snapper.rebuild_current()
        except Exception as error:
            _LOGGER.exception("Failed to save settings.")
            self.writer.report(f"Failed to save settings: {error}", StatusLevel.ERROR)
            return False

        verbose_state = "on" if verbose_f10_logging else "off"
        pending = "" if applied else " (snap score pending)"
        status = f"Settings saved: snap score {value}, F10 verbose {verbose_state}{pending}"
        level = StatusLevel.SUCCESS if applied else StatusLevel.WARNING
        self.writer.report(status, level)
        self._set_status(status)
        return True

    def refresh_vocabulary_from_ui(self) -> None:
        """Start a user-requested VAICOM vocabulary refresh on a background thread."""
        if not self._vocabulary_refresh_lock.acquire(blocking=False):
            self._set_status("Vocabulary refresh already running")
            return
        self.refresh_button.configure(state="disabled")
        self._set_status("Refreshing VAICOM vocabulary...")
        threading.Thread(daemon=True, target=self._refresh_vocabulary_from_ui).start()

    def _refresh_vocabulary_from_ui(self) -> None:
        """Run the manual vocabulary refresh and re-enable the UI action afterwards."""
        try:
            result = self.refresh_vocabulary.execute(force=True)
        except Exception as error:
            _LOGGER.exception("Manual VAICOM vocabulary refresh failed.")
            self.writer.write(f"VAICOM vocabulary refresh failed: {error}", TAG_RED)
            status = "Vocabulary refresh failed"
        else:
            status = "Vocabulary refreshed" if result.generated else f"Vocabulary: {result.reason}"
        finally:
            self._vocabulary_refresh_lock.release()
        self.window.after(0, self._finish_vocabulary_refresh, status)

    def _finish_vocabulary_refresh(self, status: str) -> None:
        """Restore the refresh button state after a manual refresh."""
        self.refresh_button.configure(state="normal")
        self._set_status(status)

    def clear_log(self) -> None:
        """Clear the status log."""
        self.writer.clear()
        self._set_status("Log cleared")

    def open_data_folder(self) -> None:
        """Open VAIVOX's per-user data folder in the system file browser."""
        try:
            if sys.platform == "win32":
                os.startfile(self.app_data_dir)
            else:
                subprocess.Popen(["xdg-open", self.app_data_dir])
        except Exception as error:
            _LOGGER.exception("Failed to open data folder.")
            self.writer.write(f"Failed to open data folder: {error}", TAG_RED)

    def _set_status_from_report(self, message: str, _level: StatusLevel) -> None:
        """Mirror the latest semantic status in the header."""
        self._set_status(message)

    def _set_status(self, message: str) -> None:
        """Set the header status text on the Tk event loop."""
        self.window.after(0, self.status_text.set, message)

    def get_theme(self) -> str:
        """Return the effective theme, resolving ``default`` to the Windows theme."""
        theme = self.config.get_theme()
        if theme == THEME_DEFAULT:
            import darkdetect

            return str(darkdetect.theme()).lower()
        return theme

    def _startup(self, _icon: object) -> None:
        """Tray setup hook: show the icon and run the control server."""
        self.icon.visible = True
        self.control_server.run()

    def _handle_exception(self, args: threading.ExceptHookArgs) -> None:
        """Handle uncaught errors raised on the control-server thread."""
        trace = traceback.format_exc()
        _LOGGER.error("Server error: %s\n\n%s", args.exc_value, trace)
        self.open_modal(f"Unexpected server error: {args.exc_value}")
        self._close()

    def _close(self, *_args: object) -> None:
        """Close the application: stop the server loop, the tray, and the window."""
        _LOGGER.info("Closing application...")
        self.exit_event.set()
        if self.api_server is not None:
            self.api_server.stop()
        self.icon.visible = False
        self.icon.stop()
        self.window.destroy()

    def _show_window(self, _icon: object, _item: object) -> None:
        """Restore the window from the system tray."""
        self.window.after(0, self.window.deiconify)

    def _withdraw_window(self) -> None:
        """Hide the window to the system tray instead of closing it."""
        self.window.withdraw()

    def open_modal(self, message: str) -> None:
        """Open a modal dialog showing ``message``."""
        from ttkbootstrap import Button, Label, Style, Toplevel

        modal = Toplevel(title=VAIVOX.name, size=(1000, 300), transient=self.window, topmost=True)
        Label(modal, text=message).pack(pady=20)
        style_factory = cast(Any, Style)
        style_factory().configure("TButton", font=("GG Sans", 11))
        Button(modal, text="Close", command=modal.destroy).pack(pady=10)
        modal.place_window_center()
        modal.grab_set()
        self.window.wait_window(modal)


def show_error_dialog(message: str) -> None:
    """Show a standalone error dialog (used before the app window exists).

    Args:
        message: The message to display.
    """
    from ttkbootstrap import Button, Label, Window

    window = Window(title=VAIVOX.name)
    Label(window, text=message).pack(pady=20, padx=20)
    Button(window, text="Close", command=window.destroy).pack(pady=10)
    window.place_window_center()
    window.mainloop()
