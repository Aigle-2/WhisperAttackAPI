"""Integration tests for the record -> transcribe -> reconcile -> route use cases.

These run the application flow end to end through in-memory fakes for every driven
port — no sockets, mic, network, or UI — verifying behaviour parity with the legacy
``WhisperServer`` (routing, blank-audio handling, status messages, fuzzy correction).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from vaivox.application.ports import SpeechToTextError, StatusLevel
from vaivox.application.queries import ComputeMetrics
from vaivox.application.record_command import (
    SimulateUtterance,
    StartRecording,
    StopAndReconcile,
)
from vaivox.application.shutdown import Shutdown
from vaivox.domain.reconciliation.model import Transcription
from vaivox.domain.reconciliation.snapper import PhraseSnapper
from vaivox.domain.telemetry.model import MatchOutcome
from vaivox.domain.vocabulary.model import (
    GovernedEntry,
    UsageStats,
    VocabularyEntry,
    VocabularyKind,
)

FUZZY_WORDS = ["Kobuleti", "Senaki", "Krymsk", "Texaco"]
_STAMP_TIME = datetime(2026, 6, 18, 12, 0, 0)


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
    def __init__(self, outcome=None):
        self.sent = []
        self._outcome = outcome

    def send(self, command):
        self.sent.append(command)
        return self._outcome  # None == unknown (a pre-return-channel plugin)


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


class FakeVocabularyRepository:
    """Records ``mark_used`` calls and serves seeded entries for attribution."""

    def __init__(self, entries=None):
        self._entries = entries or {}
        self.marked = []  # list of (ids tuple, when) for assertions

    def load(self, kind):
        return list(self._entries.get(kind, []))

    def mark_used(self, ids, when):
        self.marked.append((tuple(ids), when))


class FakeTelemetryReader:
    """Adapts a recorded-outcome list to the ``TelemetryReader`` port for ComputeMetrics."""

    def __init__(self, outcomes):
        self._outcomes = outcomes

    def recent(self, limit):
        return list(self._outcomes[-limit:]) if limit > 0 else []


def _fuzzy_entry(entry_id, term):
    """A never-used ``FUZZY_WORD`` governed entry (epoch recency, zero hits)."""
    return GovernedEntry(
        entry=VocabularyEntry(id=entry_id, kind=VocabularyKind.FUZZY_WORD, term=term),
        usage=UsageStats(last_used=datetime(1970, 1, 1), hits=0),
    )


def _make_stop(
    recorder,
    stt,
    command_sink=None,
    kneeboard_sink=None,
    config=None,
    snapper=None,
    repository=None,
):
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
        # An empty index makes the snapper a no-op, matching production with no generated
        # phrase index (behaviour parity). Tests that exercise snapping pass their own.
        snapper or PhraseSnapper([]),
        repository or FakeVocabularyRepository(),
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


def test_phrase_snapper_snaps_near_miss_before_routing():
    # A reconciled command just shy of a valid phrase is snapped to it (ADR-0011) and
    # the snap decision is recorded in telemetry.
    command_sink = FakeCommandSink()
    snapper = PhraseSnapper(["Texaco request rejoin", "Texaco request fuel"])
    use_case, _reporter, telemetry = _make_stop(
        FakeRecorder(),
        FakeSpeechToText(text="texaco request rejon"),  # near-miss, no fuzzy word fires
        command_sink=command_sink,
        config=FakeConfig(fuzzy_words=[]),
        snapper=snapper,
    )

    use_case.execute()

    assert command_sink.sent == ["Texaco request rejoin"]
    outcome = telemetry.outcomes[0]
    assert outcome.sent_text == "Texaco request rejoin"
    assert outcome.command_text == "texaco request rejon"  # pre-snap text preserved
    assert outcome.snap is not None
    assert outcome.snap.decision == "snapped"
    assert outcome.snap.candidate == "Texaco request rejoin"


def test_empty_index_snapper_is_a_no_op():
    # With no phrase index (production default) the snapper passes the command through.
    command_sink = FakeCommandSink()
    use_case, _reporter, telemetry = _make_stop(
        FakeRecorder(), FakeSpeechToText(text="kobuletti tower"), command_sink=command_sink
    )

    use_case.execute()

    assert command_sink.sent == ["Kobuleti tower"]  # only the per-token fuzzy step ran
    assert telemetry.outcomes[0].snap.decision == "raw"


def test_kneeboard_note_is_never_snapped():
    # Kneeboard notes are free text; the snapper must not touch them. Use a note that is
    # otherwise close to an index phrase, and no fuzzy words, so any change would be the
    # snapper's doing.
    kneeboard = FakeKneeboardSink()
    snapper = PhraseSnapper(["Texaco request rejoin"])
    use_case, _reporter, telemetry = _make_stop(
        FakeRecorder(),
        FakeSpeechToText(text="note texaco request rejon"),
        kneeboard_sink=kneeboard,
        config=FakeConfig(fuzzy_words=[]),
        snapper=snapper,
    )

    use_case.execute()

    assert kneeboard.sent == ["texaco request rejon"]  # unsnapped free text, verbatim
    assert telemetry.outcomes[0].destination == "kneeboard"
    assert telemetry.outcomes[0].snap is None  # not snapped on the kneeboard path


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


# -- return channel: match capture + usage stamping (ADR-0006) -----------------------


def test_matched_outcome_is_recorded_and_stamps_credited_usage():
    # A positive match is recorded in telemetry and stamps recency/hits on the vocabulary
    # entry whose term survived into the matched command (ADR-0006 §2 / ADR-0004 Tier 1).
    command_sink = FakeCommandSink(MatchOutcome(matched=True, resolved_command="Kobuleti tower"))
    repository = FakeVocabularyRepository(
        {
            VocabularyKind.FUZZY_WORD: [
                _fuzzy_entry("kobuleti", "Kobuleti"),
                _fuzzy_entry("senaki", "Senaki"),  # never appears -> never credited
            ]
        }
    )
    use_case, _reporter, telemetry = _make_stop(
        FakeRecorder(),
        FakeSpeechToText(text="kobuletti tower"),
        command_sink=command_sink,
        repository=repository,
    )

    use_case.execute()

    assert command_sink.sent == ["Kobuleti tower"]
    assert telemetry.outcomes[0].match == MatchOutcome(
        matched=True, resolved_command="Kobuleti tower"
    )
    # Only the surviving term is credited, stamped at the clock's time.
    assert repository.marked == [(("kobuleti",), _STAMP_TIME)]


def test_unmatched_outcome_is_recorded_but_stamps_nothing():
    command_sink = FakeCommandSink(MatchOutcome(matched=False, resolved_command=None))
    repository = FakeVocabularyRepository(
        {VocabularyKind.FUZZY_WORD: [_fuzzy_entry("kobuleti", "Kobuleti")]}
    )
    use_case, _reporter, telemetry = _make_stop(
        FakeRecorder(),
        FakeSpeechToText(text="kobuletti tower"),
        command_sink=command_sink,
        repository=repository,
    )

    use_case.execute()

    assert telemetry.outcomes[0].match == MatchOutcome(matched=False, resolved_command=None)
    assert repository.marked == []  # not matched -> no usage stamp


def test_unknown_outcome_against_old_plugin_preserves_parity():
    # A pre-return-channel plugin replies nothing -> the sink returns None (unknown). The
    # command still fires, telemetry records no match, and nothing is stamped (parity).
    command_sink = FakeCommandSink(None)
    repository = FakeVocabularyRepository(
        {VocabularyKind.FUZZY_WORD: [_fuzzy_entry("kobuleti", "Kobuleti")]}
    )
    use_case, _reporter, telemetry = _make_stop(
        FakeRecorder(),
        FakeSpeechToText(text="kobuletti tower"),
        command_sink=command_sink,
        repository=repository,
    )

    use_case.execute()

    assert command_sink.sent == ["Kobuleti tower"]
    assert telemetry.outcomes[0].match is None
    assert repository.marked == []


def test_kneeboard_path_never_captures_a_match_or_stamps_usage():
    repository = FakeVocabularyRepository(
        {VocabularyKind.FUZZY_WORD: [_fuzzy_entry("kobuleti", "Kobuleti")]}
    )
    use_case, _reporter, telemetry = _make_stop(
        FakeRecorder(),
        FakeSpeechToText(text="note kobuleti tower"),
        repository=repository,
    )

    use_case.execute()

    assert telemetry.outcomes[0].destination == "kneeboard"
    assert telemetry.outcomes[0].match is None
    assert repository.marked == []


def test_recorded_match_outcomes_feed_real_live_metrics():
    # End to end: routing now populates ReconciliationOutcome.match, so ComputeMetrics derives
    # a real match band from recorded telemetry instead of counting every event as unknown.
    command_sink = FakeCommandSink(MatchOutcome(matched=True, resolved_command="Kobuleti tower"))
    use_case, _reporter, telemetry = _make_stop(
        FakeRecorder(), FakeSpeechToText(text="kobuletti tower"), command_sink=command_sink
    )

    use_case.execute()

    metrics = ComputeMetrics(FakeTelemetryReader(telemetry.outcomes)).execute()
    assert metrics.total == 1
    assert metrics.match == 1
    assert metrics.unknown == 0


def test_simulate_utterance_dispatches_fuzzy_corrected_command_to_voiceattack():
    # Simulate runs the same reconcile -> snap -> route path as the PTT flow, but from text
    # and without the mic/STT, actually sending the command (ADR-0010 gated action).
    command_sink = FakeCommandSink()
    telemetry = FakeTelemetry()
    reporter = FakeReporter()
    use_case = SimulateUtterance(
        FakeConfig(),
        PhraseSnapper([]),
        command_sink,
        FakeKneeboardSink(),
        telemetry,
        reporter,
        FakeVocabularyRepository(),
        FakeClock(),
    )

    outcome = use_case.execute("kobuletti tower")

    assert command_sink.sent == ["Kobuleti tower"]  # fuzzy-corrected and dispatched for real
    assert outcome.destination == "voiceattack"
    assert outcome.sent_text == "Kobuleti tower"
    assert telemetry.outcomes[0].sent_text == "Kobuleti tower"
    assert any("Simulated utterance" in message for message in reporter.messages())


def test_simulate_utterance_routes_note_to_kneeboard():
    kneeboard = FakeKneeboardSink()
    command_sink = FakeCommandSink()
    use_case = SimulateUtterance(
        FakeConfig(fuzzy_words=[]),
        PhraseSnapper([]),
        command_sink,
        kneeboard,
        FakeTelemetry(),
        FakeReporter(),
        FakeVocabularyRepository(),
        FakeClock(),
    )

    outcome = use_case.execute("note request startup")

    assert kneeboard.sent == ["request startup"]
    assert command_sink.sent == []
    assert outcome.destination == "kneeboard"
    assert outcome.snap is None
