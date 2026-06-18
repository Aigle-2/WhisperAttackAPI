"""Use cases for the push-to-talk record -> transcribe -> reconcile -> route flow.

These orchestrate the driven ports and the reconciliation domain; they perform no
I/O themselves. The control flow mirrors the legacy ``WhisperServer`` exactly so the
user-visible behaviour (status messages, routing, blank-audio handling) is preserved.
"""

from __future__ import annotations

import logging

from vaivox.application.ports import (
    AudioRecorder,
    Clock,
    CommandSink,
    ConfigProvider,
    KneeboardSink,
    SpeechToText,
    StatusLevel,
    StatusReporter,
    TelemetrySink,
)
from vaivox.domain.reconciliation.model import ReconciliationResult
from vaivox.domain.reconciliation.pipeline import reconcile
from vaivox.domain.reconciliation.snapper import PhraseSnapper, SnapResult
from vaivox.domain.telemetry.model import ReconciliationOutcome, SnapSummary
from vaivox.domain.vocabulary.keyterms import PHONETIC_ALPHABET

_LOGGER = logging.getLogger(__name__)

_KNEEBOARD_TRIGGER = "note "
_BLANK_MARKERS = ("[BLANK_AUDIO]", "")
_FUZZY_THRESHOLD = 85


class StartRecording:
    """Begin capturing push-to-talk audio."""

    def __init__(self, recorder: AudioRecorder, reporter: StatusReporter) -> None:
        """Wire the recorder and status reporter.

        Args:
            recorder: The audio recorder port.
            reporter: The user-facing status reporter port.
        """
        self._recorder = recorder
        self._reporter = reporter

    def execute(self) -> None:
        """Start a recording, ignoring the command if one is already in progress."""
        if self._recorder.is_recording:
            _LOGGER.info("Already recording-ignoring start command.")
            self._reporter.report("Already recording—ignoring start command", StatusLevel.WARNING)
            return
        _LOGGER.info("Starting recording...")
        self._reporter.report("Starting recording...", StatusLevel.DETAIL)
        self._recorder.start()


class StopAndReconcile:
    """Stop recording, transcribe, reconcile, and route the resulting command."""

    def __init__(
        self,
        recorder: AudioRecorder,
        speech_to_text: SpeechToText,
        command_sink: CommandSink,
        kneeboard_sink: KneeboardSink,
        config: ConfigProvider,
        reporter: StatusReporter,
        clock: Clock,
        telemetry: TelemetrySink,
        snapper: PhraseSnapper,
    ) -> None:
        """Wire the ports the stop-and-reconcile flow depends on.

        Args:
            recorder: The audio recorder port.
            speech_to_text: The speech-to-text provider port.
            command_sink: The VoiceAttack command sink port.
            kneeboard_sink: The DCS kneeboard sink port.
            config: The configuration provider port (read live each utterance).
            reporter: The user-facing status reporter port.
            clock: The clock port (transcription timing).
            telemetry: The telemetry sink port.
            snapper: The conservative phrase snapper (ADR-0011) applied after
                reconciliation. With an empty phrase index it is a no-op (every command
                is sent raw), preserving behaviour when no generated index is present.
        """
        self._recorder = recorder
        self._stt = speech_to_text
        self._command_sink = command_sink
        self._kneeboard_sink = kneeboard_sink
        self._config = config
        self._reporter = reporter
        self._clock = clock
        self._telemetry = telemetry
        self._snapper = snapper

    def execute(self) -> None:
        """Stop the current recording and route the reconciled command, if any."""
        if not self._recorder.is_recording:
            _LOGGER.warning("Not currently recording-ignoring stop command.")
            self._reporter.report(
                "Not currently recording—ignoring stop command", StatusLevel.WARNING
            )
            return
        _LOGGER.info("Stopping recording...")
        self._reporter.report("Stopped recording", StatusLevel.DETAIL)

        audio_path = self._recorder.stop()
        if audio_path is None:
            self._reporter.report("Audio file not found!", StatusLevel.ERROR)
            return

        result = self._transcribe_and_reconcile(audio_path)
        if result is None or not result.command_text:
            _LOGGER.info("No transcription result.")
            self._reporter.report("No transcription result", StatusLevel.DETAIL)
            return

        self._route(result)

    def _transcribe_and_reconcile(self, audio_path: str) -> ReconciliationResult | None:
        """Transcribe and reconcile, returning ``None`` on blank audio or failure."""
        try:
            _LOGGER.info("Transcribing audio...")
            start_time = self._clock.now()
            transcription = self._stt.transcribe(audio_path)
            raw_text = transcription.text
            duration = self._clock.now() - start_time
            _LOGGER.info("Transcribing took %.3f seconds.", duration.total_seconds())
            _LOGGER.info("Raw transcription result: '%s'", raw_text)
            self._reporter.report(f"Raw transcribed text: '{raw_text}'", StatusLevel.TRANSCRIPT)

            if raw_text.strip() in _BLANK_MARKERS:
                return None

            result = reconcile(
                raw_text,
                self._config.get_word_mappings(),
                self._config.get_fuzzy_words(),
                PHONETIC_ALPHABET,
                _FUZZY_THRESHOLD,
                _FUZZY_THRESHOLD,
            )
            _LOGGER.info("Cleaned transcription: %s", result.cleaned_text)
            _LOGGER.info("Fuzzy-corrected transcription: %s", result.command_text)
            return result
        except Exception as error:
            # Broad guard for parity with the legacy transcribe path: any provider or
            # reconciliation failure surfaces as one error line, never crashes the loop.
            _LOGGER.error("Failed to transcribe audio: %s", error)
            self._reporter.report(f"Failed to transcribe audio: {error}", StatusLevel.ERROR)
            return None

    def _route(self, result: ReconciliationResult) -> None:
        """Route the reconciled command to the kneeboard or VoiceAttack.

        Kneeboard notes (``note ...``) are free text and are never snapped — only the
        VoiceAttack command path runs through the phrase snapper (ADR-0011), which is a
        no-op when the phrase index is empty.
        """
        command = result.command_text
        snap: SnapResult | None = None
        if command.lower().startswith(_KNEEBOARD_TRIGGER):
            note_text = command[len(_KNEEBOARD_TRIGGER) :].strip()
            self._kneeboard_sink.send(note_text)
            destination, sent_text = "kneeboard", note_text
        else:
            snap = self._snapper.snap(command)
            if snap.text != command:
                _LOGGER.info("Phrase snap: '%s' -> '%s' (%.1f)", command, snap.text, snap.score)
            self._command_sink.send(snap.text)
            destination, sent_text = "voiceattack", snap.text

        self._telemetry.record(
            ReconciliationOutcome(
                raw_text=result.raw_text,
                cleaned_text=result.cleaned_text,
                command_text=result.command_text,
                sent_text=sent_text,
                destination=destination,
                snap=_snap_summary(snap),
            )
        )


def _snap_summary(snap: SnapResult | None) -> SnapSummary | None:
    """Flatten a :class:`SnapResult` into the serializable telemetry summary.

    Args:
        snap: The snapper's result, or ``None`` for the kneeboard path (not snapped).

    Returns:
        A :class:`SnapSummary` for telemetry, or ``None`` when the command was not
        snapped (the kneeboard path), keeping the prior telemetry record shape there.
    """
    if snap is None:
        return None
    return SnapSummary(
        decision=str(snap.decision),
        candidate=snap.candidate,
        score=snap.score,
        near_misses=tuple((nm.phrase, nm.score) for nm in snap.near_misses),
    )
