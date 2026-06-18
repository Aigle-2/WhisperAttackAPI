import os
import sys
import ctypes
import logging
import threading
import traceback
from tkinter import PhotoImage, font, LEFT, DISABLED, WORD, W, NSEW
import darkdetect
from pystray import Icon, Menu, MenuItem
from ttkbootstrap import Window, Toplevel, Button, Label, Style
from ttkbootstrap.widgets.scrolled import ScrolledText
from ttkbootstrap.constants import *
from PIL import Image
from pid import PidFile, PidFileError
# VAIVOX migration (Phase 2+): make the in-repo ``src/vaivox`` package importable
# when launching from source. No-op once the package is installed or frozen.
_VAIVOX_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if os.path.isdir(_VAIVOX_SRC) and _VAIVOX_SRC not in sys.path:
    sys.path.append(_VAIVOX_SRC)

from configuration import WhisperAttackConfiguration, ConfigurationError
from theme import THEME_DEFAULT, THEME_DARK, TAG_BLUE, TAG_GREY, TAG_RED
from writer import WhisperAttackWriter
from whisper_server import WhisperServer
from word_mappings import WhisperAttackWordMappings

# This event is used to stop the server socket and shutdown.
exit_event = threading.Event()

APPLICATION_VERSION = "1.2.2"

# File paths for configuration, word mappings, and fuzzy words
APPLICATION_PATH = ""
if getattr(sys, 'frozen', False):
    # If the application is run as a bundle, the PyInstaller bootloader
    # extends the sys module by a flag frozen=True
    APPLICATION_PATH = os.path.dirname(sys.executable)
else:
    APPLICATION_PATH = os.path.dirname(__file__)

LOCAL_APPDATA_DIR = os.getenv('LOCALAPPDATA')
WHISPER_APPDATA_DIR = os.path.join(LOCAL_APPDATA_DIR , "WhisperAttack")
# Create the AppData directory for WhisterAttack if it does not already exist
os.makedirs(WHISPER_APPDATA_DIR, exist_ok=True)

def start_logging() -> None:
    """
    Start logging to the %LOCALAPPDATA%\\WhisperAttack directory.
    """
    log_file = os.path.join(WHISPER_APPDATA_DIR, "WhisperAttack.log")
    logging.basicConfig(
        filename=log_file,
        filemode='w',
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.getLogger().setLevel(logging.INFO)

class WhisperAttack:
    """
    Class for the main WhisperAttack application.
    """
    def __init__(self, root: Window):
        start_logging()

        logging.info("WhisperAttack version: %s", APPLICATION_VERSION)
        logging.info("WhisperAttack location: %s", APPLICATION_PATH)

        self.root = root
        self.config = WhisperAttackConfiguration(APPLICATION_PATH, WHISPER_APPDATA_DIR)

        theme = self.get_theme()
        if theme == THEME_DARK:
            self.root.style.theme_use("darkly")
        else:
            self.root.style.theme_use("flatly")

        custom_font = font.Font(family="GG Sans", size=11)
        Style().configure('TButton', font=custom_font)
        Style().configure('TLabel', font=custom_font)

        text_area = ScrolledText(
            self.root,
            wrap=WORD,
            width=100,
            height=50,
            state=DISABLED,
            autohide=True,
            font=custom_font
        )
        text_area.grid(row=0, column=0, sticky=NSEW, padx=10, pady=10)

        self.add_icon = PhotoImage(file="add_icon.png")
        add_word_mapping_button = Button(
            self.root,
            text="Add word mapping",
            style="secondary.TButton",
            image=self.add_icon,
            compound=LEFT,
            command=self.add_word_mapping
        )
        add_word_mapping_button.grid(row=1, column=0, sticky=W, pady=10, padx=10)

        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        self.writer = WhisperAttackWriter(theme, text_area)

        self.writer.write("Loaded configuration:", TAG_BLUE)
        self.writer.write_dict(self.config.get_safe_configuration(), TAG_GREY)
        self.write_startup_context()

        self.whisper_server = WhisperServer(self.config, self.writer, self.shutdown, exit_event)

        threading.excepthook = self.handle_exception
        threading.Thread(daemon=True, target=lambda: icon.run(setup=self.startup)).start()

    def write_startup_context(self) -> None:
        """
        Write the startup vocabulary summary to the UI.
        """
        word_mappings = self.config.get_word_mappings()
        fuzzy_words = self.config.get_fuzzy_words()

        self.writer.write("Loaded post-processing word mappings:", TAG_BLUE)
        self.writer.write(f"{len(word_mappings)} mappings", TAG_GREY)
        self.writer.write_dict(word_mappings, TAG_GREY)

        self.writer.write("Loaded fuzzy correction words:", TAG_BLUE)
        self.writer.write(f"{len(fuzzy_words)} words: {', '.join(fuzzy_words)}", TAG_GREY)

        self.write_stt_keyterm_context()

    def write_stt_keyterm_context(self) -> None:
        """
        Write the effective STT keyterm context without dumping the whole VAICOM list.
        """
        provider = self.config.get_stt_backend()
        source_counts = self.config.get_stt_keyterm_source_counts()
        all_keyterms = self.config.get_stt_keyterms()
        budget = self.config.get_provider_stt_keyterm_budget(provider)
        budgeted = self.config.get_provider_budgeted_stt_keyterm_details(provider, log_result=False)
        supported_providers = {"elevenlabs", "deepgram", "openai"}

        source_summary = ", ".join(
            f"{source}={count}" for source, count in source_counts.items()
        ) or "none"
        limit_summary = self.format_keyterm_budget(budget)

        self.writer.write("Loaded STT keyterm context:", TAG_BLUE)
        self.writer.write(f"provider: {provider}", TAG_GREY)
        self.writer.write(f"sources: {source_summary}", TAG_GREY)
        self.writer.write(f"available: {len(all_keyterms)} unique terms", TAG_GREY)

        if provider not in supported_providers:
            self.writer.write(f"effective: not used by {provider}", TAG_GREY)
            return
        if provider == "openai" and not self.config.get_provider_bool("openai", "include_keyterms_in_prompt", True):
            self.writer.write("effective: disabled by openai_include_keyterms_in_prompt", TAG_GREY)
            return

        target = "OpenAI prompt" if provider == "openai" else provider
        self.writer.write(f"effective: {len(budgeted.keyterms)} terms sent to {target}", TAG_GREY)
        if limit_summary:
            self.writer.write(f"limits: {limit_summary}", TAG_GREY)
        if budgeted.skipped_too_long or budgeted.omitted_by_term_limit or budgeted.omitted_by_char_limit:
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

    def format_keyterm_budget(self, budget) -> str:
        limits = []
        if budget.max_terms is not None:
            limits.append(f"max_terms={budget.max_terms}")
        if budget.max_term_chars is not None:
            limits.append(f"max_term_chars={budget.max_term_chars}")
        if budget.max_total_chars is not None:
            limits.append(f"max_total_chars={budget.max_total_chars}")
        return ", ".join(limits)

    def shutdown(self) -> None:
        """
        Callback handler once the whisper server has shutdown
        to close the application
        """
        close(icon)

    def add_word_mapping(self) -> None:
        """
        Open the configuration dialog to add word mappings
        """
        def update_word_mapping(aliases: str, replacement: str):
            try:
                self.config.add_word_mapping(WHISPER_APPDATA_DIR, aliases, replacement)
                self.writer.write("Added new word mapping:", TAG_BLUE)
                self.writer.write(f"{aliases}: {replacement}", TAG_GREY)
            except ConfigurationError as error:
                self.writer.write(error, TAG_RED)
        WhisperAttackWordMappings(self.root, update_word_mapping)

    def get_theme(self) -> str:
        """
        Returns the name of the theme to be used when displaying
        UI elements. When the configuration is set to "default" then
        the name returned will be the current Windows theme.
        """
        theme = self.config.get_theme()
        if theme == THEME_DEFAULT:
            return darkdetect.theme().lower()
        return theme

    def startup(self, _icon) -> None:
        """
        Start the WhisperAttack server.
        """
        icon.visible = True
        self.whisper_server.run_server()

    def handle_exception(self, args) -> None:
        """
        Handle errors from the Whisper Server thread
        """
        trace = traceback.format_exc()
        logging.error("Server error: %s\n\n%s", args.exc_value, trace)
        open_modal(f"Unexpected server error: {args.exc_value}")
        exit(icon)

window = Window(title="WhisperAttack", iconphoto="whisper_attack_icon.png")

def close(_icon) -> None:
    """
    Close the application.
    """
    logging.info("Closing application...")
    exit_event.set()
    icon.visible = False
    icon.stop()
    window.destroy()

def show_window(_icon, _item) -> None:
    """
    Show the window from the system tray.
    """
    window.after(0, window.deiconify)

def withdraw_window() -> None:
    """
    Hide the window when closed, returns it to the system tray.
    """
    window.withdraw()

def open_modal(message: str) -> None:
    """
    Open a modal dialog to display messages.
    """
    modal = Toplevel(
        title="WhisperAttack",
        size=(1000, 300),
        transient=window,
        topmost=True
    )
    label = Label(modal, text=message)
    label.pack(pady=20)
    Style().configure('TButton', font=('GG Sans', 11))
    close_button = Button(modal, text="Close", command=modal.destroy)
    close_button.pack(pady=10)
    modal.place_window_center()
    modal.grab_set()
    window.wait_window(modal)

window.protocol('WM_DELETE_WINDOW', withdraw_window)

# The Whisper system tray icon
image = Image.open("whisper_attack_icon.png")
icon = Icon(
    "WA", image, "WhisperAttack",
    menu=Menu(MenuItem("Show", show_window), MenuItem("Exit", close))
)

###############################################################################
# MAIN
###############################################################################
def main():
    """
    Run the WhisperAttack application.
    This is run using a lock file so that only one instance
    can be run at a time.
    """
    # Lock file to create to prevent multiple instances being run
    lock_file = os.path.join(WHISPER_APPDATA_DIR, 'whisper_attack')
    with PidFile(lock_file):
        WhisperAttack(window)
        window.mainloop()

if __name__ == "__main__":
    try:
        main()
    except PidFileError as pid_error:
        # Error means possibly another instance of application
        # is already running, this second attempt will be killed.
        open_modal("WhisperAttack is already running")
    except Exception as e:
        TRACE = traceback.format_exc()
        logging.error("Server error: %s\n\n%s", e, TRACE)
        open_modal(f"Unexpected server error: {e}")
        close(icon)
