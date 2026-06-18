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
    ConfigProvider,
    KneeboardSink,
    PhraseMatcher,
    SpeechToText,
    StatusLevel,
    StatusReporter,
    TelemetrySink,
    VocabularyRepository,
)
from vaivox.domain.reconciliation.model import ReconciliationResult
from vaivox.domain.reconciliation.pipeline import reconcile
from vaivox.domain.reconciliation.snapper import SnapResult
from vaivox.domain.telemetry.model import MatchOutcome, ReconciliationOutcome, SnapSummary
from vaivox.domain.vocabulary.governor import VocabularyGovernor
from vaivox.domain.vocabulary.keyterms import PHONETIC_ALPHABET
from vaivox.domain.vocabulary.model import VocabularyKind

_LOGGER = logging.getLogger(__name__)

_KNEEBOARD_TRIGGER = "note "
_BLANK_MARKERS = ("[BLANK_AUDIO]", "")
_FUZZY_THRESHOLD = 85

#: The stateless Tier 1 attribution service (ADR-0004); reused across utterances.
_GOVERNOR = VocabularyGovernor()

#: Vocabulary kinds attribution can credit from the live pipeline today. ``ALIAS`` is
#: reserved/unpopulated, so only fuzzy words and word mappings are considered.
_ATTRIBUTABLE_KINDS = (VocabularyKind.FUZZY_WORD, VocabularyKind.WORD_MAPPING)


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
        snapper: PhraseMatcher,
        repository: VocabularyRepository,
    ) -> None:
        """Wire the ports the stop-and-reconcile flow depends on.

        Args:
            recorder: The audio recorder port.
            speech_to_text: The speech-to-text provider port.
            command_sink: The VoiceAttack command sink port.
            kneeboard_sink: The DCS kneeboard sink port.
            config: The configuration provider port (read live each utterance).
            reporter: The user-facing status reporter port.
            clock: The clock port (transcription timing and the usage-stamp time).
            telemetry: The telemetry sink port.
            snapper: The phrase matcher (ADR-0011) applied after reconciliation —
                a frozen :class:`~vaivox.domain.reconciliation.snapper.PhraseSnapper` or
                the idle-hot-reloadable adapter (ADR-0009), behind the same port. With an
                empty phrase index it is a no-op (every command is sent raw), preserving
                behaviour when no generated index is present.
            repository: The vocabulary repository port, stamped with usage on a matched
                command (ADR-0006 §2). A repository with no seeded entries is a clean no-op.
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
        self._repository = repository

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
        """Route the reconciled command to the kneeboard or VoiceAttack (shared logic)."""
        route_command(
            result,
            snapper=self._snapper,
            command_sink=self._command_sink,
            kneeboard_sink=self._kneeboard_sink,
            telemetry=self._telemetry,
            repository=self._repository,
            clock=self._clock,
        )


@dataclass(frozen=True)
class RouteOutcome:
    """The result of routing a reconciled command (ADR-0010 simulate + the PTT flow).

    Attributes:
        destination: ``"voiceattack"`` or ``"kneeboard"``.
        sent_text: The exact text dispatched to that destination.
        snap: The phrase-snap result on the VoiceAttack path, or ``None`` for a kneeboard
            note (never snapped).
        match: The plugin's match outcome on the VoiceAttack path (ADR-0006), or ``None``
            for a kneeboard note or an unknown result (no/garbled plugin reply).
    """

    destination: str
    sent_text: str
    snap: SnapResult | None
    match: MatchOutcome | None = None


def route_command(
    result: ReconciliationResult,
    *,
    snapper: PhraseMatcher,
    command_sink: CommandSink,
    kneeboard_sink: KneeboardSink,
    telemetry: TelemetrySink,
    repository: VocabularyRepository,
    clock: Clock,
) -> RouteOutcome:
    """Route a reconciled command, record telemetry, and stamp usage (PTT + simulate).

    Kneeboard notes (``note ...``) are free text and are never snapped — only the
    VoiceAttack command path runs through the phrase snapper (ADR-0011), which is a no-op
    when the phrase index is empty. Extracted so the push-to-talk flow
    (:class:`StopAndReconcile`) and the gated simulate action (:class:`SimulateUtterance`,
    ADR-0010) dispatch and record identically — there is exactly one routing path.

    On the VoiceAttack path the sink returns the plugin's :class:`MatchOutcome` (ADR-0006);
    it is recorded in telemetry, and on a positive match the contributing vocabulary entries
    are credited with usage (ADR-0004 attribution). The kneeboard path never matches, so it
    is never stamped.

    Args:
        result: The staged reconciliation result to route.
        snapper: The phrase matcher applied on the VoiceAttack path.
        command_sink: The VoiceAttack command sink (returns the match outcome).
        kneeboard_sink: The DCS kneeboard sink.
        telemetry: The telemetry sink the outcome is recorded to.
        repository: The vocabulary repository stamped with usage on a match.
        clock: The clock supplying the usage-stamp time.

    Returns:
        The :class:`RouteOutcome` describing where the command went, the snap result, and
        the match outcome.
    """
    command = result.command_text
    snap: SnapResult | None = None
    match: MatchOutcome | None = None
    if command.lower().startswith(_KNEEBOARD_TRIGGER):
        note_text = command[len(_KNEEBOARD_TRIGGER) :].strip()
        kneeboard_sink.send(note_text)
        destination, sent_text = "kneeboard", note_text
    else:
        snap = snapper.snap(command)
        if snap.text != command:
            _LOGGER.info("Phrase snap: '%s' -> '%s' (%.1f)", command, snap.text, snap.score)
        match = command_sink.send(snap.text)
        destination, sent_text = "voiceattack", snap.text
        if match is not None and match.matched:
            # Only a positive match stamps usage; the matched command (resolved_command,
            # which equals sent_text for VA's exact-name check) carries the surviving tokens.
            _stamp_matched_usage(match.resolved_command or sent_text, repository, clock)

    telemetry.record(
        ReconciliationOutcome(
            raw_text=result.raw_text,
            cleaned_text=result.cleaned_text,
            command_text=result.command_text,
            sent_text=sent_text,
            destination=destination,
            match=match,
            snap=_snap_summary(snap),
        )
    )
    return RouteOutcome(destination=destination, sent_text=sent_text, snap=snap, match=match)


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
        config: ConfigProvider,
        snapper: PhraseMatcher,
        command_sink: CommandSink,
        kneeboard_sink: KneeboardSink,
        telemetry: TelemetrySink,
        reporter: StatusReporter,
        repository: VocabularyRepository,
        clock: Clock,
    ) -> None:
        """Wire the ports the simulate action routes through (mirrors the PTT flow).

        Args:
            config: The configuration provider (word mappings / fuzzy words, read live).
            snapper: The phrase matcher applied on the VoiceAttack path.
            command_sink: The VoiceAttack command sink.
            kneeboard_sink: The DCS kneeboard sink.
            telemetry: The telemetry sink the outcome is recorded to.
            reporter: The status reporter (surfaces the agent-triggered dispatch).
            repository: The vocabulary repository stamped with usage on a match (ADR-0006).
            clock: The clock supplying the usage-stamp time.
        """
        self._config = config
        self._snapper = snapper
        self._command_sink = command_sink
        self._kneeboard_sink = kneeboard_sink
        self._telemetry = telemetry
        self._reporter = reporter
        self._repository = repository
        self._clock = clock

    def execute(self, text: str) -> RouteOutcome:
        """Reconcile ``text`` and dispatch it for real, returning the route outcome.

        Args:
            text: The utterance text to simulate (as if it had been transcribed).

        Returns:
            The :class:`RouteOutcome` for the dispatched command.
        """
        result = reconcile(
            text,
            self._config.get_word_mappings(),
            self._config.get_fuzzy_words(),
            PHONETIC_ALPHABET,
            _FUZZY_THRESHOLD,
            _FUZZY_THRESHOLD,
        )
        outcome = route_command(
            result,
            snapper=self._snapper,
            command_sink=self._command_sink,
            kneeboard_sink=self._kneeboard_sink,
            telemetry=self._telemetry,
            repository=self._repository,
            clock=self._clock,
        )
        self._reporter.report(
            f"Simulated utterance: '{text}' -> sent '{outcome.sent_text}' to {outcome.destination}",
            StatusLevel.DETAIL,
        )
        return outcome


def _stamp_matched_usage(matched_text: str, repository: VocabularyRepository, clock: Clock) -> None:
    """Credit the vocabulary entries whose term survived into a matched command (ADR-0006 §2).

    Runs Tier 1 token-provenance attribution (ADR-0004) per vocabulary kind and stamps
    recency/hits on the credited entries through the repository.

    **Reachable scope today:** the live reconciliation pipeline reads word-mappings/fuzzy
    from ``config`` (not the repository) and emits no per-edit provenance, so attribution is
    approximated by *surface form* — a repository entry (seeded by
    ``tools/migrate_vocabulary.py`` from the same vocabulary) is credited when one of its
    canonical ``term`` tokens appears in the matched command. This can over-credit a term the
    speaker simply uttered, but for an LRU recency signal that is the safe error direction (a
    useful term is kept, not decayed); a positive match never *under*-credits a term that did
    fire. Precise per-edit provenance (Tier 1 by exact edit, Tier 2 counterfactual) waits on
    the pipeline reading vocab from the :class:`~vaivox.application.ports.VocabularyRepository`
    (an ADR-0009 follow-up). A repository with no seeded entries is a clean no-op.

    Args:
        matched_text: The command VoiceAttack matched (its tokens are the survivors).
        repository: The vocabulary repository to credit usage in.
        clock: The clock supplying the stamp time.
    """
    matched_tokens = matched_text.split()
    if not matched_tokens:
        return
    credited: list[str] = []
    for kind in _ATTRIBUTABLE_KINDS:
        governed = repository.load(kind)
        if not governed:
            continue
        # Within a kind, ids are unique (migration enforces it), so the id-keyed mapping is
        # safe; the matched tokens are the "survivors" Tier 1 checks each term's output against.
        edit_output_tokens = {entry.id: tuple(entry.entry.term.split()) for entry in governed}
        credited.extend(_GOVERNOR.attribute_tier1(matched_tokens, edit_output_tokens))
    if credited:
        repository.mark_used(credited, clock.now())


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
