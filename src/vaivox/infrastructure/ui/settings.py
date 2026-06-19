"""Modal dialog for runtime-editable VAIVOX settings.

ttkbootstrap and tkinter are imported lazily inside the constructor so the module
imports without the UI stack installed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ttkbootstrap import Window


class VaivoxSettings:
    """Show a modal that edits phrase-snap calibration and diagnostic settings."""

    def __init__(
        self,
        root: Window,
        required_score: float,
        verbose_f10_logging: bool,
        save_settings: Callable[[float, bool], bool],
    ) -> None:
        """Build and display the settings modal.

        Args:
            root: The parent application window.
            required_score: The current ``snap_high`` threshold.
            verbose_f10_logging: The current ``mission_f10_verbose_logging`` flag.
            save_settings: Callback invoked with ``(score, verbose_f10_logging)`` on OK;
                returns ``True`` when the settings were saved (closing the modal).
        """
        from tkinter import LEFT, BooleanVar, StringVar, font

        from ttkbootstrap import Button, Checkbutton, Entry, Frame, Label, Toplevel

        self.save_settings = save_settings

        modal_width = 540
        modal_height = 280
        parent_x = root.winfo_x()
        parent_y = root.winfo_y()
        parent_width = root.winfo_width()
        parent_height = root.winfo_height()
        x = parent_x + (parent_width // 2) - (modal_width // 2)
        y = parent_y + (parent_height // 2) - (modal_height // 2)

        modal = Toplevel(
            title="Settings",
            size=(modal_width, modal_height),
            position=(x, y),
            transient=root,
        )
        modal.grab_set()

        score = StringVar(value=f"{required_score:.1f}")
        verbose = BooleanVar(value=verbose_f10_logging)
        error = StringVar(value="")
        custom_font = font.Font(family="GG Sans", size=11)

        score_frame = Frame(modal)
        score_frame.pack(pady=(22, 8), padx=16, fill="x")
        Label(score_frame, text="Phrase snap required score").pack(side=LEFT, padx=5)
        Entry(score_frame, textvariable=score, font=custom_font, width=8).pack(side=LEFT, padx=5)

        verbose_frame = Frame(modal)
        verbose_frame.pack(pady=(4, 8), padx=16, fill="x")
        Checkbutton(
            verbose_frame,
            text="Verbose F10 command-pull logging",
            variable=verbose,
            bootstyle="round-toggle",
        ).pack(side=LEFT, padx=5)

        Label(modal, textvariable=error, bootstyle="danger").pack(pady=(0, 4), padx=20, anchor="w")

        def save() -> None:
            raw_score = score.get().strip().replace(",", ".")
            try:
                parsed = float(raw_score)
            except ValueError:
                error.set("Enter a score from 0 to 100.")
                return
            if not 0.0 <= parsed <= 100.0:
                error.set("Enter a score from 0 to 100.")
                return
            if self.save_settings(parsed, bool(verbose.get())):
                modal.destroy()

        button_frame = Frame(modal)
        button_frame.pack(pady=28, padx=16, fill="x")
        Button(
            button_frame,
            text="Ok",
            style="primary.TButton",
            command=save,
        ).pack(side=LEFT, padx=10)
        Button(
            button_frame,
            text="Cancel",
            style="secondary.TButton",
            command=modal.destroy,
        ).pack(side=LEFT, padx=10)
