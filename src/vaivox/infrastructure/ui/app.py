"""Windowed application + system-tray adapter (the driver UI).

This is the ttkbootstrap window and pystray tray relocated from the legacy
``whisper_attack`` god-module. It owns the widgets, prints the startup context, and
runs the control server (built by the composition root) on the tray thread. All UI
libraries are imported lazily so the module imports without them installed.
"""

from __future__ import annotations

import logging
import threading
import traceback
from os import path
from threading import Event
from typing import TYPE_CHECKING, Any

from vaivox import composition
from vaivox.infrastructure.config.settings import ConfigurationError, WhisperAttackConfiguration
from vaivox.infrastructure.ui.theme import (
    TAG_BLUE,
    TAG_GREY,
    TAG_RED,
    THEME_DARK,
    THEME_DEFAULT,
)
from vaivox.infrastructure.ui.word_mappings import WhisperAttackWordMappings
from vaivox.infrastructure.ui.writer import TkStatusWriter

if TYPE_CHECKING:
    from vaivox.domain.vocabulary.keyterms import KeytermBudget

_LOGGER = logging.getLogger(__name__)

APPLICATION_VERSION = "1.2.2"

_SUPPORTED_KEYTERM_PROVIDERS = {"elevenlabs", "deepgram", "openai"}


class WhisperAttackApp:
    """The WhisperAttack window, system-tray icon, and control-server thread."""

    def __init__(self, app_path: str, app_data_dir: str) -> None:
        """Build the window, wire the control server, and start the tray thread.

        Args:
            app_path: Directory holding the bundled assets and default config.
            app_data_dir: The per-user data directory for overrides and logs.
        """
        from tkinter import DISABLED, LEFT, NSEW, WORD, PhotoImage, W, font

        from PIL import Image
        from pystray import Icon, Menu, MenuItem
        from ttkbootstrap import Button, Style, Window
        from ttkbootstrap.widgets.scrolled import ScrolledText

        _LOGGER.info("WhisperAttack version: %s", APPLICATION_VERSION)
        _LOGGER.info("WhisperAttack location: %s", app_path)

        self.app_path = app_path
        self.app_data_dir = app_data_dir
        self.exit_event = Event()

        self.window = Window(
            title="WhisperAttack",
            iconphoto=path.join(app_path, "whisper_attack_icon.png"),
        )
        self.config = WhisperAttackConfiguration(app_path, app_data_dir)

        theme = self.get_theme()
        self.window.style.theme_use("darkly" if theme == THEME_DARK else "flatly")

        custom_font = font.Font(family="GG Sans", size=11)
        Style().configure("TButton", font=custom_font)
        Style().configure("TLabel", font=custom_font)

        text_area = ScrolledText(
            self.window,
            wrap=WORD,
            width=100,
            height=50,
            state=DISABLED,
            autohide=True,
            font=custom_font,
        )
        text_area.grid(row=0, column=0, sticky=NSEW, padx=10, pady=10)

        self.add_icon: Any = PhotoImage(file=path.join(app_path, "add_icon.png"))
        add_word_mapping_button = Button(
            self.window,
            text="Add word mapping",
            style="secondary.TButton",
            image=self.add_icon,
            compound=LEFT,
            command=self.add_word_mapping,
        )
        add_word_mapping_button.grid(row=1, column=0, sticky=W, pady=10, padx=10)

        self.window.grid_rowconfigure(0, weight=1)
        self.window.grid_columnconfigure(0, weight=1)

        self.writer = TkStatusWriter(theme, text_area)
        self.writer.write("Loaded configuration:", TAG_BLUE)
        self.writer.write_dict(dict(self.config.get_safe_configuration()), TAG_GREY)
        self.write_startup_context()

        wired = composition.build(
            config=self.config,
            reporter=self.writer,
            exit_event=self.exit_event,
            request_shutdown=self._close,
        )
        self.control_server = wired.control_server

        image = Image.open(path.join(app_path, "whisper_attack_icon.png"))
        self.icon = Icon(
            "WA",
            image,
            "WhisperAttack",
            menu=Menu(MenuItem("Show", self._show_window), MenuItem("Exit", self._close)),
        )
        self.window.protocol("WM_DELETE_WINDOW", self._withdraw_window)

        threading.excepthook = self._handle_exception
        threading.Thread(daemon=True, target=lambda: self.icon.run(setup=self._startup)).start()

    def run(self) -> None:
        """Run the Tk main loop (blocks until the window is destroyed)."""
        self.window.mainloop()

    def write_startup_context(self) -> None:
        """Write the startup vocabulary summary to the UI."""
        word_mappings = self.config.get_word_mappings()
        fuzzy_words = self.config.get_fuzzy_words()

        self.writer.write("Loaded post-processing word mappings:", TAG_BLUE)
        self.writer.write(f"{len(word_mappings)} mappings", TAG_GREY)
        self.writer.write_dict(dict(word_mappings), TAG_GREY)

        self.writer.write("Loaded fuzzy correction words:", TAG_BLUE)
        self.writer.write(f"{len(fuzzy_words)} words: {', '.join(fuzzy_words)}", TAG_GREY)

        self.write_stt_keyterm_context()

    def write_stt_keyterm_context(self) -> None:
        """Write the effective STT keyterm context without dumping the whole list."""
        provider = self.config.get_stt_backend()
        source_counts = self.config.get_stt_keyterm_source_counts()
        all_keyterms = self.config.get_stt_keyterms()
        budget = self.config.get_provider_stt_keyterm_budget(provider)
        budgeted = self.config.get_provider_budgeted_stt_keyterm_details(provider, log_result=False)

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
                self.config.add_word_mapping(self.app_data_dir, aliases, replacement)
                self.writer.write("Added new word mapping:", TAG_BLUE)
                self.writer.write(f"{aliases}: {replacement}", TAG_GREY)
            except ConfigurationError as error:
                self.writer.write(str(error), TAG_RED)

        WhisperAttackWordMappings(self.window, update_word_mapping)

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

        modal = Toplevel(
            title="WhisperAttack", size=(1000, 300), transient=self.window, topmost=True
        )
        Label(modal, text=message).pack(pady=20)
        Style().configure("TButton", font=("GG Sans", 11))
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

    window = Window(title="WhisperAttack")
    Label(window, text=message).pack(pady=20, padx=20)
    Button(window, text="Close", command=window.destroy).pack(pady=10)
    window.place_window_center()
    window.mainloop()
