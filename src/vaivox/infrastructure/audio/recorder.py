"""Microphone recorder adapter built on ``sounddevice`` + ``soundfile``.

The heavy audio libraries are imported lazily inside :meth:`SoundDeviceRecorder.start`
so the package (and the test suite) imports without them installed.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_AUDIO_FILENAME = "whisper_temp_recording.wav"


class SoundDeviceRecorder:
    """Capture push-to-talk audio to a WAV file in the system temp directory."""

    def __init__(self, audio_file: str | None = None, sample_rate: int = _SAMPLE_RATE) -> None:
        """Configure the output file and sample rate.

        Args:
            audio_file: Override the output WAV path (defaults to the temp directory).
            sample_rate: Capture sample rate in Hz.
        """
        self._audio_file = audio_file or os.path.join(tempfile.gettempdir(), _AUDIO_FILENAME)
        self._sample_rate = sample_rate
        self._recording = False
        self._wave_file: Any = None
        self._stream: Any = None

    @property
    def is_recording(self) -> bool:
        """Whether a recording is currently in progress."""
        return self._recording

    @property
    def audio_file(self) -> str:
        """The path the recorder writes captured audio to."""
        return self._audio_file

    def start(self) -> None:
        """Open the output file and begin streaming microphone audio into it."""
        import sounddevice as sd
        import soundfile as sf

        self._wave_file = sf.SoundFile(
            self._audio_file,
            mode="w",
            samplerate=self._sample_rate,
            channels=1,
            subtype="FLOAT",
        )

        def audio_callback(
            indata: object, _frames: int, _time_info: object, status: object
        ) -> None:
            if status:
                _LOGGER.info("Audio Status: %s", status)
            self._wave_file.write(indata)

        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            callback=audio_callback,
        )
        self._stream.start()
        self._recording = True

    def stop(self) -> str | None:
        """Stop streaming, close the file, and return its path if it was written.

        Returns:
            The recorded WAV path, or ``None`` if the file is missing afterwards.
        """
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self._wave_file.close()
        self._wave_file = None
        self._recording = False
        time.sleep(0.01)
        _LOGGER.debug("Checking if file exists: %s", self._audio_file)
        if os.path.exists(self._audio_file):
            size = os.path.getsize(self._audio_file)
            _LOGGER.info("Audio file size = %s bytes", size)
            return self._audio_file
        _LOGGER.error("Audio file '%s' not found", self._audio_file)
        return None
