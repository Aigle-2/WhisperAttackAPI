"""Unit tests for the sounddevice recorder adapter's failure paths."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from vaivox.infrastructure.audio.recorder import SoundDeviceRecorder


class FakeWaveFile:
    def __init__(self) -> None:
        self.closed = False

    def write(self, _data) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeStream:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


def test_stop_without_start_is_safe() -> None:
    recorder = SoundDeviceRecorder()

    assert recorder.stop() is None
    assert recorder.is_recording is False


def test_stop_closes_partial_state(tmp_path) -> None:
    audio_file = tmp_path / "recording.wav"
    audio_file.write_bytes(b"RIFF")
    recorder = SoundDeviceRecorder(audio_file=str(audio_file))
    stream = FakeStream()
    wave_file = FakeWaveFile()
    recorder._stream = stream
    recorder._wave_file = wave_file
    recorder._recording = True

    assert recorder.stop() == str(audio_file)
    assert stream.stopped is True
    assert stream.closed is True
    assert wave_file.closed is True
    assert recorder.is_recording is False


def test_start_failure_closes_open_wave_file(monkeypatch) -> None:
    wave_file = FakeWaveFile()

    def failing_input_stream(**_kwargs):
        raise RuntimeError("microphone unavailable")

    fake_sounddevice = SimpleNamespace(InputStream=failing_input_stream)
    fake_soundfile = SimpleNamespace(SoundFile=lambda *_args, **_kwargs: wave_file)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice)
    monkeypatch.setitem(sys.modules, "soundfile", fake_soundfile)
    recorder = SoundDeviceRecorder()

    with pytest.raises(RuntimeError, match="microphone unavailable"):
        recorder.start()

    assert wave_file.closed is True
    assert recorder.is_recording is False
