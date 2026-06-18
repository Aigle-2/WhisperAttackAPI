"""Integration tests for the record -> transcribe -> reconcile -> route use cases.

These run the application flow end to end through in-memory fakes for every driven
port — no sockets, mic, network, or UI — verifying behaviour parity with the legacy
``WhisperServer`` (routing, blank-audio handling, status messages, fuzzy correction).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from vaivox.application.ports import SpeechToTextError, StatusLevel
from vaivox.application.record_command import StartRecording, StopAndReconcile
from vaivox.application.shutdown import Shutdown
from vaivox.domain.reconciliation.model import Transcription

FUZZY_WORDS = ["Kobuleti", "Senaki", "Krymsk", "Texaco"]


class FakeRecorder:
    def __init__(self, recording=True, stop_path="audio.wav"):
        self._recording = recording
        self._stop_path = stop_path
        self.started = False

    @property
    def is_recording(self):
        return self._recording

    def start(self):
        self.started = True
        self._recording = True

    def stop(self):
        self._recording = False
        return self._stop_path


class FakeSpeechToText:
    def __init__(self, text="", error=None):
        self._text = text
        self._error = error
        self.loaded = False

    def load(self):
        self.loaded = True

    def transcribe(self, audio_path):
        if self._error is not None:
            raise self._error
        return Transcription(text=self._text)


class FakeCommandSink:
    def __init__(self):
        self.sent = []

    def send(self, command):
        self.sent.append(command)


class FakeKneeboardSink:
    def __init__(self):
        self.sent = []

    def send(self, note_text):
        self.sent.append(note_text)


class FakeConfig:
    def __init__(self, word_mappings=None, fuzzy_words=FUZZY_WORDS):
        self._word_mappings = word_mappings or {}
        self._fuzzy_words = fuzzy_words

    def get_word_mappings(self):
        return self._word_mappings

    def get_fuzzy_words(self):
        return self._fuzzy_words


class FakeReporter:
    def __init__(self):
        self.lines = []

    def report(self, message, level=StatusLevel.INFO):
        self.lines.append((message, level))

    def messages(self):
        return [message for message, _level in self.lines]


class FakeClock:
    def now(self):
        return datetime(2026, 6, 18, 12, 0, 0)


class FakeTelemetry:
    def __init__(self):
        self.outcomes = []

    def record(self, outcome):
        self.outcomes.append(outcome)


def _make_stop(recorder, stt, command_sink=None, kneeboard_sink=None, config=None):
    reporter = FakeReporter()
    telemetry = FakeTelemetry()
    use_case = StopAndReconcile(
        recorder,
        stt,
        command_sink or FakeCommandSink(),
        kneeboard_sink or FakeKneeboardSink(),
        config or FakeConfig(),
        reporter,
        FakeClock(),
        telemetry,
    )
    return use_case, reporter, telemetry


def test_full_flow_routes_fuzzy_corrected_command_to_voiceattack():
    command_sink = FakeCommandSink()
    use_case, reporter, telemetry = _make_stop(
        FakeRecorder(), FakeSpeechToText(text="kobuletti tower"), command_sink=command_sink
    )

    use_case.execute()

    # Fuzzy correction snapped "kobuletti" -> "Kobuleti" on the way to the sink.
    assert command_sink.sent == ["Kobuleti tower"]
    assert (reporter.messages()[0]) == "Stopped recording"
    assert "Raw transcribed text: 'kobuletti tower'" in reporter.messages()
    assert telemetry.outcomes[0].destination == "voiceattack"
    assert telemetry.outcomes[0].sent_text == "Kobuleti tower"
    assert telemetry.outcomes[0].raw_text == "kobuletti tower"


def test_note_prefix_routes_to_kneeboard_with_trigger_stripped():
    kneeboard = FakeKneeboardSink()
    command_sink = FakeCommandSink()
    use_case, _reporter, telemetry = _make_stop(
        FakeRecorder(),
        FakeSpeechToText(text="note request startup"),
        command_sink=command_sink,
        kneeboard_sink=kneeboard,
    )

    use_case.execute()

    assert kneeboard.sent == ["request startup"]
    assert command_sink.sent == []
    assert telemetry.outcomes[0].destination == "kneeboard"
    assert telemetry.outcomes[0].sent_text == "request startup"


@pytest.mark.parametrize("raw", ["[BLANK_AUDIO]", "", "   "])
def test_blank_audio_reports_no_result_and_routes_nothing(raw):
    command_sink = FakeCommandSink()
    use_case, reporter, telemetry = _make_stop(
        FakeRecorder(), FakeSpeechToText(text=raw), command_sink=command_sink
    )

    use_case.execute()

    assert command_sink.sent == []
    assert telemetry.outcomes == []
    assert "No transcription result" in reporter.messages()


def test_missing_audio_file_reports_error():
    use_case, reporter, telemetry = _make_stop(
        FakeRecorder(stop_path=None), FakeSpeechToText(text="anything")
    )

    use_case.execute()

    assert ("Audio file not found!", StatusLevel.ERROR) in reporter.lines
    assert telemetry.outcomes == []


def test_transcription_failure_reports_error_then_no_result():
    use_case, reporter, telemetry = _make_stop(
        FakeRecorder(), FakeSpeechToText(error=SpeechToTextError("boom"))
    )

    use_case.execute()

    messages = reporter.messages()
    assert "Failed to transcribe audio: boom" in messages
    assert "No transcription result" in messages
    assert telemetry.outcomes == []


def test_stop_when_not_recording_warns_and_does_nothing():
    command_sink = FakeCommandSink()
    use_case, reporter, telemetry = _make_stop(
        FakeRecorder(recording=False), FakeSpeechToText(text="anything"), command_sink=command_sink
    )

    use_case.execute()

    assert command_sink.sent == []
    assert telemetry.outcomes == []
    assert any(level is StatusLevel.WARNING for _message, level in reporter.lines)


def test_start_recording_starts_when_idle():
    recorder = FakeRecorder(recording=False)
    reporter = FakeReporter()

    StartRecording(recorder, reporter).execute()

    assert recorder.started is True
    assert ("Starting recording...", StatusLevel.DETAIL) in reporter.lines


def test_start_recording_ignores_when_already_recording():
    recorder = FakeRecorder(recording=True)
    reporter = FakeReporter()

    StartRecording(recorder, reporter).execute()

    assert recorder.started is False
    assert any(level is StatusLevel.WARNING for _message, level in reporter.lines)


def test_shutdown_invokes_callback():
    reporter = FakeReporter()
    called = []

    Shutdown(lambda: called.append(True), reporter).execute()

    assert called == [True]
    assert any("shutdown" in message.lower() for message in reporter.messages())
