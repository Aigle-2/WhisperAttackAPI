import os
import socket
import time
import logging
import unicodedata
import tempfile
import re
from datetime import datetime
from threading import Event
from typing import Callable
import keyboard
import sounddevice as sd
import soundfile as sf
import pyperclip
from rapidfuzz import process
from text2digits import text2digits
from wcwidth import wcswidth
from configuration import WhisperAttackConfiguration
from stt_backends.base import SpeechToTextBackendError
from stt_backends.factory import create_stt_backend
from stt_backends.keyterms import PHONETIC_ALPHABET
from writer import WhisperAttackWriter
from theme import TAG_BLUE, TAG_GREEN, TAG_GREY, TAG_ORANGE, TAG_RED

###############################################################################
# CONFIG
###############################################################################
HOST = '127.0.0.1'
PORT = 65432

# Library to convert textual numbers to their numerical values
t2d = text2digits.Text2Digits()

# Use the system's temporary folder for the WAV file.
TEMP_DIR = tempfile.gettempdir()
AUDIO_FILE = os.path.join(TEMP_DIR, "whisper_temp_recording.wav")
SAMPLE_RATE = 16000

###############################################################################
# PHONETIC ALPHABET
###############################################################################
phonetic_alphabet = PHONETIC_ALPHABET

###############################################################################
# FUZZY MATCH + CLEANUP
###############################################################################
def correct_dcs_and_phonetics_separately(
    text: str,
    dcs_list: list[str],
    phonetic_list: list[str],
    dcs_threshold=85,
    phonetic_threshold=85
) -> str:
    """
    Applies fuzzy matching for DCS callsigns and the phonetic alphabet.
    """
    tokens = text.split()
    corrected_tokens = []
    dcs_lower = [x.lower() for x in dcs_list]
    phon_lower = [x.lower() for x in phonetic_list]

    for token in tokens:
        if len(token) < 6:
            corrected_tokens.append(token)
            continue

        t_lower = token.lower()
        dcs_match = process.extractOne(t_lower, dcs_lower, score_cutoff=dcs_threshold)
        phon_match = process.extractOne(t_lower, phon_lower, score_cutoff=phonetic_threshold)
        best_token = token
        best_score = 0

        if dcs_match is not None:
            match_name_dcs, score_dcs, _ = dcs_match
            if score_dcs > best_score:
                best_score = score_dcs
                for orig in dcs_list:
                    if orig.lower() == match_name_dcs:
                        best_token = orig
                        break

        if phon_match is not None:
            match_name_phon, score_phon, _ = phon_match
            if score_phon > best_score:
                best_score = score_phon
                for orig in phonetic_list:
                    if orig.lower() == match_name_phon:
                        best_token = orig
                        break

        corrected_tokens.append(best_token)
    return " ".join(corrected_tokens)

def replace_word_mappings(word_mappings: dict[str, str], text: str) -> str:
    """
    Replace transcribed words with custom words from their mapped values.
    """
    for word, replacement in word_mappings.items():
        pattern = rf"\b{re.escape(word)}\b"
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text

def custom_cleanup_text(text: str, word_mappings: dict[str, str]) -> str:
    """
    Performs several cleanup steps on the transcribed text.
    """
    text = unicodedata.normalize('NFC', text.strip())
    text = replace_word_mappings(word_mappings, text)
    text = t2d.convert(text)
    text = re.sub(r"(?<=\d)-(?=\d)", " ", text)
    text = re.sub(r'\b0\d+\b', lambda x: ' '.join(x.group()), text)
    text = re.sub(r"([^\w\d\s])*(?![\w\-\w])(?![^-])?", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def format_for_dcs_kneeboard(text: str, line_length: int) -> str:
    """
    Formats text for word wrapping for use in the DCS kneeboard
    This is based on the original code from BojotecX WhisperKneeboard
    https://github.com/BojoteX/KneeboardWhisper
    """
    # Split the text into words and handle punctuation
    words = re.findall(r'\S+|\n', text)

    lines = []
    current_words = []
    current_len = 0

    for word in words:
        word_len = wcswidth(word)

        # If adding the next word exceeds the line length
        if current_len + word_len + (len(current_words)) > line_length:
            line = justify_line(current_words, line_length)
            lines.append(line)
            current_words = [word]
            current_len = word_len
        else:
            current_words.append(word)
            current_len += word_len

    # Justify the last line (left-justified)
    if current_words:
        last_line = ' '.join(current_words).ljust(line_length)
        lines.append(last_line)

    # Ensure the last line is completely blank
    lines.append(' ' * line_length)

    return '\n'.join(lines)

def justify_line(words: list[str], line_length: int):
    """
    Justify the words from left to right
    """
    if len(words) == 1:
        # If there's only one word, left-justify it
        return words[0].ljust(line_length)

    # Calculate the total display width of words
    total_words_length = sum(wcswidth(word) for word in words)
    total_spaces = line_length - total_words_length
    gaps = len(words) - 1
    spaces_between_words = [total_spaces // gaps] * gaps

    # Distribute the remaining spaces from left to right
    for i in range(total_spaces % gaps):
        spaces_between_words[i] += 1

    # Build the justified line
    line = ''
    for i, word in enumerate(words[:-1]):
        line += word + ' ' * spaces_between_words[i]
    line += words[-1]  # Add the last word without extra spaces after it
    return line

###############################################################################
# WHISPER SERVER
###############################################################################
class WhisperServer:
    """
    Class that runs a socket server to listen for incoming commands.
    Commands will start or stop the recording of audio to a wav file.
    Once recording has stopped the audio will be transcribed to text and
    sent to either VoiceAttack or the DCS kneeboard.
    """
    def __init__(self, config: WhisperAttackConfiguration, writer: WhisperAttackWriter, shutdown: Callable, exit_event: Event):
        self.config = config
        self.writer = writer
        self.exit_event = exit_event
        self.shutdown = shutdown
        self.stt_backend = None
        self.recording = False
        self.audio_file = AUDIO_FILE
        self.wave_file = None
        self.stream = None

        self.voiceattack_host = self.config.get_voiceattack_host()
        self.voiceattack_port = self.config.get_voiceattack_port()

    def load_stt_backend(self, config: WhisperAttackConfiguration) -> None:
        """
        Loads the configured speech-to-text backend.
        """
        backend_name = config.get_stt_backend()
        logging.info("Loading STT backend '%s' ...", backend_name)
        self.writer.write(f"Loading STT backend ({backend_name}) ...")
        self.stt_backend = create_stt_backend(config)
        self.stt_backend.load()
        logging.info("Successfully loaded STT backend '%s'", backend_name)
        self.writer.write(f"Successfully loaded STT backend ({backend_name})", TAG_GREEN)
        return None

    def start_recording(self) -> None:
        """
        Begin recording to a wav file.
        """
        if self.recording:
            logging.info("Already recording—ignoring start command.")
            self.writer.write("Already recording—ignoring start command", TAG_ORANGE)
            return None
        logging.info("Starting recording...")
        self.writer.write("Starting recording...", TAG_GREY)
        self.wave_file = sf.SoundFile(
            self.audio_file,
            mode='w',
            samplerate=SAMPLE_RATE,
            channels=1,
            subtype='FLOAT'
        )
        def audio_callback(indata, _frames, _time_info, status):
            if status:
                logging.info("Audio Status: %s", status)
            self.wave_file.write(indata)
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype='float32',
            callback=audio_callback
        )
        self.stream.start()
        self.recording = True
        return None

    def stop_and_transcribe(self) -> None:
        """
        Stops the currently running recording to then have this transcribed.
        """
        if not self.recording:
            logging.warning("Not currently recording—ignoring stop command.")
            self.writer.write("Not currently recording—ignoring stop command", TAG_ORANGE)
            return None
        logging.info("Stopping recording...")
        self.writer.write("Stopped recording", TAG_GREY)
        self.stream.stop()
        self.stream.close()
        self.stream = None
        self.wave_file.close()
        self.wave_file = None
        self.recording = False
        time.sleep(0.01)
        logging.debug("Checking if file exists: %s", self.audio_file)
        if os.path.exists(self.audio_file):
            size = os.path.getsize(self.audio_file)
            logging.info("Audio file size = %s bytes", size)
        else:
            logging.error(("Audio file '%s' not found", self.audio_file))
            self.writer.write("Audio file not found!", TAG_RED)
            return None
        recognized_text = self.transcribe_audio(self.audio_file)
        if recognized_text:
            trigger_phrase = "note "
            if recognized_text.lower().startswith(trigger_phrase):
                self.send_to_dcs_kneeboard(recognized_text)
            else:
                self.send_to_voiceattack(recognized_text)
        else:
            logging.info("No transcription result.")
            self.writer.write("No transcription result", TAG_GREY)
        return None

    def transcribe_audio(self, audio_path: str) -> str | None:
        """
        Transcribes the recorded audio to text and then returns the final result
        after running it through functions to cleanup the raw text.
        """
        try:
            logging.info("Transcribing audio...")
            start_time = datetime.now()
            if self.stt_backend is None:
                raise SpeechToTextBackendError("STT backend is not loaded.")
            result = self.stt_backend.transcribe(audio_path)
            raw_text = result.text

            end_time = datetime.now()
            duration = end_time - start_time
            logging.info(f"Transcribing took {duration.total_seconds():.3f} seconds.")
            logging.info("Raw transcription result: '%s'", raw_text)
            self.writer.write(f"Raw transcribed text: '{raw_text}'", TAG_BLUE)
            # Ignore blank audio as nothing has been recorded
            if raw_text.strip() == "[BLANK_AUDIO]" or raw_text.strip() == "":
                return None
            cleaned_text = custom_cleanup_text(raw_text, self.config.get_word_mappings())
            fuzzy_corrected_text = correct_dcs_and_phonetics_separately(
                cleaned_text,
                self.config.get_fuzzy_words(),
                phonetic_alphabet,
                dcs_threshold=85,
                phonetic_threshold=85
            )
            logging.info("Cleaned transcription: %s", cleaned_text)
            logging.info("Fuzzy-corrected transcription: %s", fuzzy_corrected_text)
            return fuzzy_corrected_text
        except Exception as e:
            logging.error("Failed to transcribe audio: %s", e)
            self.writer.write(f"Failed to transcribe audio: {e}", TAG_RED)
            return None

    def send_to_dcs_kneeboard(self, text: str) -> None:
        """
        Copy the text to the clipboard and then send to
        the DCS kneeboard.
        """
        # Strip the "note" trigger phrase and then format into multiple
        # lines to fit the kneeboard page
        text_for_kneeboard = format_for_dcs_kneeboard(text[5:].strip(), self.config.get_text_line_length())
        pyperclip.copy(text_for_kneeboard)
        logging.info("Text copied to clipboard for DCS kneeboard.")
        try:
            keyboard.press_and_release('ctrl+alt+p')
            self.writer.write(f"Sent text to DCS: {text_for_kneeboard}", TAG_GREEN)
            logging.info("DCS kneeboard populated")
        except Exception as e:
            logging.error("Failed to simulate keyboard shortcut: %s", e)
            self.writer.write(f"Failed to simulate keyboard shortcut: {e}", TAG_RED)

    def send_to_voiceattack(self, text: str) -> None:
        """
        Sends the transcribed text to VoiceAttack.
        """
        try:
            logging.info("Sending recognized text to VoiceAttack: %s", text)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                client_socket.connect((self.voiceattack_host, self.voiceattack_port))
                client_socket.sendall(text.encode())

            logging.info("Sent text to VoiceAttack: %s", text)
            self.writer.write(f"Sent text to VoiceAttack: {text}", TAG_GREEN)
        except Exception as e:
            logging.error("Error calling VoiceAttack (%s:%s): %s", self.voiceattack_host, self.voiceattack_port, e)
            self.writer.write(f"Error calling VoiceAttack: {e}", TAG_RED)
        finally:
            client_socket.close()

    def handle_command(self, cmd: str) -> None:
        """
        Triggers the operation for the associated command that was received.
        """
        cmd = cmd.strip().lower()
        logging.info("Received command: %s", cmd)
        if cmd == "start":
            self.start_recording()
        elif cmd == "stop":
            self.stop_and_transcribe()
        elif cmd == "shutdown":
            logging.info("Received shutdown command. Stopping server...")
            self.writer.write("Received shutdown command. Stopping server...")
            self.shutdown()
        else:
            logging.warning("Unknown command: %s", cmd)
            self.writer.write(f"Unknown command: {cmd}", TAG_ORANGE)

    def run_server(self) -> None:
        """
        Starts a socket server and listens for incoming commands.
        """
        try:
            self.load_stt_backend(self.config)
        except SpeechToTextBackendError as e:
            logging.error("Failed to load STT backend: %s", e)
            self.writer.write(f"Failed to load STT backend: {e}", TAG_RED)
            return None
        except Exception as e:
            logging.exception("Unexpected failure while loading STT backend.")
            self.writer.write(f"Failed to load STT backend: {e}", TAG_RED)
            return None

        logging.info("Server started and listening on %s:%s", HOST, PORT)
        self.writer.write(f"Server started and listening on {HOST}:{PORT}", TAG_GREEN)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((HOST, PORT))
            s.listen()
            s.settimeout(1.0)

            while not self.exit_event.is_set():
                try:
                    conn, _ = s.accept()
                    with conn:
                        data = conn.recv(1024).decode('utf-8')
                        if data:
                            self.handle_command(data)
                except socket.timeout:
                    continue
                except Exception as e:
                    logging.error("Socket error: %s", e)
                    self.writer.write(f"Socket error: {e}", TAG_RED)
                    continue
        if self.recording:
            self.stop_and_transcribe()

        logging.info("Server has shut down cleanly.")
        self.writer.write("Server has shut down cleanly.")
