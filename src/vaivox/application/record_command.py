"""Use cases for the push-to-talk record -> transcribe -> reconcile -> route flow.

These orchestrate the driven ports and the reconciliation domain; they perform no
I/O themselves. The control flow mirrors the legacy ``WhisperServer`` exactly so the
user-visible behaviour (status messages, routing, blank-audio handling) is preserved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from vaivox.application.ports import (
    AudioRecorder,
    Clock,
    CommandSink,
    KneeboardSink,
    PhraseMatcher,
    SpeechToText,
    StatusLevel,
    StatusReporter,
    TelemetrySink,
)
from vaivox.application.reconcile_text import ReconcileText
from vaivox.application.usage_stamping import UsageStamper
from vaivox.domain.reconciliation.model import ReconciliationResult
from vaivox.domain.reconciliation.snapper import SnapResult
from vaivox.domain.telemetry.model import ReconciliationOutcome, SnapSummary

_LOGGER = logging.getLogger(__name__)

_KNEEBOARD_TRIGGER = "note "
_BLANK_MARKERS = ("[BLANK_AUDIO]", "")


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
        reconcile_text: ReconcileText,
        reporter: StatusReporter,
        clock: Clock,
        telemetry: TelemetrySink,
        snapper: PhraseMatcher,
        usage_stamper: UsageStamper | None = None,
    ) -> None:
        """Wire the ports the stop-and-reconcile flow depends on.

        Args:
            recorder: The audio recorder port.
            speech_to_text: The speech-to-text provider port.
            command_sink: The VoiceAttack command sink port.
            kneeboard_sink: The DCS kneeboard sink port.
            reconcile_text: The single reconciliation entry point (ADR-0004); reads the
                vocabulary live each utterance and runs the domain pipeline (phonetic
                alphabet + the domain-default fuzzy threshold).
            reporter: The user-facing status reporter port.
            clock: The clock port (transcription timing).
            telemetry: The telemetry sink port.
            snapper: The phrase matcher (ADR-0011) applied after reconciliation —
                a frozen :class:`~vaivox.domain.reconciliation.snapper.PhraseSnapper` or
                the idle-hot-reloadable adapter (ADR-0009), behind the same port. With an
                empty phrase index it is a no-op (every command is sent raw), preserving
                behaviour when no generated index is present.
            usage_stamper: Optional vocabulary usage stamper (ADR-0004 governance). When
                supplied, the VoiceAttack dispatch path credits the contributing vocabulary
                entries (Tier 1 attribution) and stamps their recency/hits. ``None`` (the
                default) disables stamping — used by tests and any flow that has no
                repository to write back to.
        """
        self._recorder = recorder
        self._stt = speech_to_text
        self._command_sink = command_sink
        self._kneeboard_sink = kneeboard_sink
        self._reconcile_text = reconcile_text
        self._reporter = reporter
        self._clock = clock
        self._telemetry = telemetry
        self._snapper = snapper
        self._usage_stamper = usage_stamper

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

            result = self._reconcile_text.execute(raw_text)
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
        """Route the reconciled command to the kneeboard or VoiceAttack (shared logic)."""
        route_command(
            result,
            snapper=self._snapper,
            command_sink=self._command_sink,
            kneeboard_sink=self._kneeboard_sink,
            telemetry=self._telemetry,
            usage_stamper=self._usage_stamper,
        )


@dataclass(frozen=True)
class RouteOutcome:
    """The result of routing a reconciled command (ADR-0010 simulate + the PTT flow).

    Attributes:
        destination: ``"voiceattack"`` or ``"kneeboard"``.
        sent_text: The exact text dispatched to that destination.
        snap: The phrase-snap result on the VoiceAttack path, or ``None`` for a kneeboard
            note (never snapped).
    """

    destination: str
    sent_text: str
    snap: SnapResult | None


def route_command(
    result: ReconciliationResult,
    *,
    snapper: PhraseMatcher,
    command_sink: CommandSink,
    kneeboard_sink: KneeboardSink,
    telemetry: TelemetrySink,
    usage_stamper: UsageStamper | None = None,
) -> RouteOutcome:
    """Route a reconciled command and record telemetry (shared by PTT + simulate).

    Kneeboard notes (``note ...``) are free text and are never snapped — only the
    VoiceAttack command path runs through the phrase snapper (ADR-0011), which is a no-op
    when the phrase index is empty. Extracted so the push-to-talk flow
    (:class:`StopAndReconcile`) and the gated simulate action (:class:`SimulateUtterance`,
    ADR-0010) dispatch and record identically — there is exactly one routing path.

    On the VoiceAttack path only, an optional :class:`UsageStamper` credits the vocabulary
    entries whose surface form survived into the dispatched text (ADR-0004 governance,
    Tier 1 attribution). Kneeboard notes never stamp — they are free text, not vocabulary.
    The stamp runs **after** the command is sent so a stamping hiccup can never delay or
    block the dispatch, and the stamper itself swallows its own errors.

    **No real match signal:** without the C# return channel (ADR-0006) the stamp credits on
    *dispatch*, not on a confirmed VoiceAttack match — see :class:`UsageStamper`.

    Args:
        result: The staged reconciliation result to route.
        snapper: The phrase matcher applied on the VoiceAttack path.
        command_sink: The VoiceAttack command sink.
        kneeboard_sink: The DCS kneeboard sink.
        telemetry: The telemetry sink the outcome is recorded to.
        usage_stamper: Optional vocabulary usage stamper invoked on the VoiceAttack path;
            ``None`` disables stamping (tests / flows with no repository).

    Returns:
        The :class:`RouteOutcome` describing where the command went and the snap result.
    """
    command = result.command_text
    snap: SnapResult | None = None
    if command.lower().startswith(_KNEEBOARD_TRIGGER):
        note_text = command[len(_KNEEBOARD_TRIGGER) :].strip()
        kneeboard_sink.send(note_text)
        destination, sent_text = "kneeboard", note_text
    else:
        snap = snapper.snap(command)
        if snap.text != command:
            _LOGGER.info("Phrase snap: '%s' -> '%s' (%.1f)", command, snap.text, snap.score)
        command_sink.send(snap.text)
        destination, sent_text = "voiceattack", snap.text
        if usage_stamper is not None:
            usage_stamper.stamp(sent_text)

    telemetry.record(
        ReconciliationOutcome(
            raw_text=result.raw_text,
            cleaned_text=result.cleaned_text,
            command_text=result.command_text,
            sent_text=sent_text,
            destination=destination,
            snap=_snap_summary(snap),
        )
    )
    return RouteOutcome(destination=destination, sent_text=sent_text, snap=snap)


class SimulateUtterance:
    """Run text through reconcile -> snap -> route, actually dispatching it (ADR-0010).

    Unlike :class:`~vaivox.application.queries.DryRunReconcile` (which only *stages* the
    transformations), simulate **sends** the resulting command to VoiceAttack (or the
    kneeboard) and records telemetry — the full push-to-talk path minus the mic and STT.
    It is a gated debug/agent action (off by default) and reports the dispatch to the UI so
    an agent-triggered command is never invisible to the user.
    """

    def __init__(
        self,
        reconcile_text: ReconcileText,
        snapper: PhraseMatcher,
        command_sink: CommandSink,
        kneeboard_sink: KneeboardSink,
        telemetry: TelemetrySink,
        reporter: StatusReporter,
        usage_stamper: UsageStamper | None = None,
    ) -> None:
        """Wire the ports the simulate action routes through (mirrors the PTT flow).

        Args:
            reconcile_text: The single reconciliation entry point (ADR-0004); reads the
                vocabulary live and runs the same pipeline as the PTT path.
            snapper: The phrase matcher applied on the VoiceAttack path.
            command_sink: The VoiceAttack command sink.
            kneeboard_sink: The DCS kneeboard sink.
            telemetry: The telemetry sink the outcome is recorded to.
            reporter: The status reporter (surfaces the agent-triggered dispatch).
            usage_stamper: Optional vocabulary usage stamper. Simulate is a *real* dispatch
                (ADR-0010), so it shares the PTT path's stamping when wired; ``None``
                disables it.
        """
        self._reconcile_text = reconcile_text
        self._snapper = snapper
        self._command_sink = command_sink
        self._kneeboard_sink = kneeboard_sink
        self._telemetry = telemetry
        self._reporter = reporter
        self._usage_stamper = usage_stamper

    def execute(self, text: str) -> RouteOutcome:
        """Reconcile ``text`` and dispatch it for real, returning the route outcome.

        Args:
            text: The utterance text to simulate (as if it had been transcribed).

        Returns:
            The :class:`RouteOutcome` for the dispatched command.
        """
        result = self._reconcile_text.execute(text)
        outcome = route_command(
            result,
            snapper=self._snapper,
            command_sink=self._command_sink,
            kneeboard_sink=self._kneeboard_sink,
            telemetry=self._telemetry,
            usage_stamper=self._usage_stamper,
        )
        self._reporter.report(
            f"Simulated utterance: '{text}' -> sent '{outcome.sent_text}' to {outcome.destination}",
            StatusLevel.DETAIL,
        )
        return outcome


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
