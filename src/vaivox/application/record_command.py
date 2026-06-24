"""Use cases for the push-to-talk record -> transcribe -> reconcile -> route flow.

These orchestrate the driven ports and the reconciliation domain; they perform no
I/O themselves. The control flow mirrors the legacy ``WhisperServer`` exactly so the
user-visible behaviour (status messages, routing, blank-audio handling) is preserved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from vaivox.application.learn_from_outcome import LearnFromOutcome
from vaivox.application.ports import (
    AudioRecorder,
    Clock,
    CommandDispatcher,
    CommandSurfaceMatcher,
    KneeboardSink,
    PhraseMatcher,
    ReconciliationVocabulary,
    SpeechToText,
    StatusLevel,
    StatusReporter,
    TelemetrySink,
    VocabularyRepository,
)
from vaivox.domain.commands.model import (
    CommandResolution,
    CommandResolutionDecision,
    DispatchOutcome,
    DispatchTargetKind,
    VaicomF10Action,
    VoiceAttackCommand,
)
from vaivox.domain.reconciliation.model import ReconciliationResult
from vaivox.domain.reconciliation.pipeline import reconcile
from vaivox.domain.reconciliation.snapper import NearMiss, SnapDecision, SnapResult
from vaivox.domain.telemetry.model import (
    CommandResolutionSummary,
    MatchOutcome,
    ReconciliationOutcome,
    SnapSummary,
)
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
        command_dispatcher: CommandDispatcher,
        kneeboard_sink: KneeboardSink,
        vocabulary: ReconciliationVocabulary,
        reporter: StatusReporter,
        clock: Clock,
        telemetry: TelemetrySink,
        surface_matcher: CommandSurfaceMatcher,
        snapper: PhraseMatcher,
        repository: VocabularyRepository,
        learn_from_outcome: LearnFromOutcome | None = None,
    ) -> None:
        """Wire the ports the stop-and-reconcile flow depends on.

        Args:
            recorder: The audio recorder port.
            speech_to_text: The speech-to-text provider port.
            command_dispatcher: The typed command dispatcher port.
            kneeboard_sink: The DCS kneeboard sink port.
            vocabulary: The reconciliation vocabulary port (read live each utterance).
            reporter: The user-facing status reporter port.
            clock: The clock port (transcription timing and the usage-stamp time).
            telemetry: The telemetry sink port.
            surface_matcher: The command-surface resolver applied before legacy fallback.
            snapper: The phrase matcher (ADR-0011) applied after reconciliation —
                a frozen :class:`~vaivox.domain.reconciliation.snapper.PhraseSnapper` or
                the idle-hot-reloadable adapter (ADR-0009), behind the same port. With an
                empty phrase index it is a no-op (every command is sent raw), preserving
                behaviour when no generated index is present.
            repository: The vocabulary repository port, stamped with usage on a matched
                command (ADR-0006 §2). A repository with no seeded entries is a clean no-op.
            learn_from_outcome: The vocabulary learning use case (ADR-0006), or ``None`` to
                disable learning. When wired, a confirmed not-matched / snap-abstained
                VoiceAttack dispatch derives a learned mapping proposal (propose-only by
                default). Best-effort and never fatal to dispatch.
        """
        self._recorder = recorder
        self._stt = speech_to_text
        self._command_dispatcher = command_dispatcher
        self._kneeboard_sink = kneeboard_sink
        self._vocabulary = vocabulary
        self._reporter = reporter
        self._clock = clock
        self._telemetry = telemetry
        self._surface_matcher = surface_matcher
        self._snapper = snapper
        self._repository = repository
        self._learn_from_outcome = learn_from_outcome

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
                self._vocabulary.get_word_mappings(),
                self._vocabulary.get_fuzzy_words(),
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
            surface_matcher=self._surface_matcher,
            snapper=self._snapper,
            command_dispatcher=self._command_dispatcher,
            kneeboard_sink=self._kneeboard_sink,
            telemetry=self._telemetry,
            repository=self._repository,
            clock=self._clock,
            reporter=self._reporter,
            learn_from_outcome=self._learn_from_outcome,
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
    resolution: CommandResolution | None = None
    dispatch: DispatchOutcome | None = None


def route_command(
    result: ReconciliationResult,
    *,
    surface_matcher: CommandSurfaceMatcher,
    snapper: PhraseMatcher,
    command_dispatcher: CommandDispatcher,
    kneeboard_sink: KneeboardSink,
    telemetry: TelemetrySink,
    repository: VocabularyRepository,
    clock: Clock,
    reporter: StatusReporter | None = None,
    learn_from_outcome: LearnFromOutcome | None = None,
) -> RouteOutcome:
    """Route a reconciled command, record telemetry, and stamp usage (PTT + simulate).

    Kneeboard notes (``note ...``) are free text and are never snapped — only the
    VoiceAttack command path runs through the phrase snapper (ADR-0011), which is a no-op
    when the phrase index is empty. Extracted so the push-to-talk flow
    (:class:`StopAndReconcile`) and the gated simulate action (:class:`SimulateUtterance`,
    ADR-0010) dispatch and record identically — there is exactly one routing path.

    A resolved command surface dispatches its typed target: a static
    :class:`~vaivox.domain.commands.model.VoiceAttackCommand` goes to VoiceAttack (returning
    the plugin's :class:`MatchOutcome`, ADR-0006), while a live
    :class:`~vaivox.domain.commands.model.VaicomF10Action` fires DCS ``doAction`` over the
    UDP F10 sink (fire-and-forget — no match, ADR-0012). When nothing resolves, the legacy
    phrase snapper picks a static VoiceAttack command. Positive VoiceAttack matches credit
    the contributing vocabulary entries with usage (ADR-0004 attribution).

    Args:
        result: The staged reconciliation result to route.
        surface_matcher: The command-surface resolver applied before legacy fallback.
        snapper: The phrase matcher applied on the VoiceAttack path.
        command_dispatcher: The typed command dispatcher.
        kneeboard_sink: The DCS kneeboard sink.
        telemetry: The telemetry sink the outcome is recorded to.
        repository: The vocabulary repository stamped with usage on a match.
        clock: The clock supplying the usage-stamp time.
        reporter: Optional user-facing reporter for phrase-snap diagnostics.
        learn_from_outcome: Optional vocabulary learning use case (ADR-0006). On the
            VoiceAttack branch only, a confirmed not-matched / snap-abstained outcome is
            turned into a learned mapping proposal (propose-only by default). Best-effort;
            it swallows its own errors and never affects dispatch. ``None`` disables it.

    Returns:
        The :class:`RouteOutcome` describing where the command went, the snap result, and
        the match outcome.
    """
    command = result.command_text
    snap: SnapResult | None = None
    match: MatchOutcome | None = None
    resolution: CommandResolution | None = None
    dispatch: DispatchOutcome | None = None
    if command.lower().startswith(_KNEEBOARD_TRIGGER):
        note_text = command[len(_KNEEBOARD_TRIGGER) :].strip()
        kneeboard_sink.send(note_text)
        dispatch = DispatchOutcome(
            target_kind="kneeboard",
            accepted=True,
            resolved_target=note_text,
            detail="kneeboard note",
        )
        destination, sent_text = "kneeboard", note_text
    else:
        resolution = surface_matcher.resolve(command)
        _report_resolution_diagnostics(command, resolution, reporter)
        if (
            resolution.decision is CommandResolutionDecision.RESOLVED
            and resolution.surface is not None
        ):
            surface = resolution.surface
            dispatch_result = command_dispatcher.dispatch(surface.dispatch_target)
            dispatch = dispatch_result.dispatch
            match = dispatch_result.match
            destination = dispatch.target_kind
            sent_text = dispatch.resolved_target or surface.label
            if not dispatch.accepted:
                _report_dispatch_rejection(dispatch, reporter)
        elif resolution.decision is CommandResolutionDecision.REJECTED or (
            resolution.decision is CommandResolutionDecision.ABSTAINED
            and resolution.surface is not None
            and resolution.surface.dispatch_target.target_kind
            is DispatchTargetKind.VAICOM_F10_ACTION
        ):
            rejected_surface = resolution.surface
            target_kind = (
                DispatchTargetKind.VAICOM_F10_ACTION.value
                if rejected_surface is None
                else rejected_surface.dispatch_target.target_kind.value
            )
            detail = resolution.reason or "ambiguous mission F10 command; nothing dispatched"
            dispatch = DispatchOutcome(
                target_kind=target_kind,
                accepted=False,
                resolved_target=(None if rejected_surface is None else rejected_surface.label),
                detail=detail,
            )
            destination = "rejected"
            sent_text = command
        else:
            snap = snapper.snap(command)
            _report_snap_diagnostics(command, snap, reporter)
            if snap.text != command:
                _LOGGER.info("Phrase snap: '%s' -> '%s' (%.1f)", command, snap.text, snap.score)
            dispatch_result = command_dispatcher.dispatch(VoiceAttackCommand(snap.text))
            dispatch = dispatch_result.dispatch
            match = dispatch_result.match
            destination = DispatchTargetKind.VOICEATTACK.value
            sent_text = dispatch.resolved_target or snap.text
        if match is not None and match.matched:
            # Only a positive match stamps usage; the submitted profile phrase carries the
            # surviving tokens used by Tier 1 attribution.
            _stamp_matched_usage(match.resolved_command or sent_text, repository, clock)
        if learn_from_outcome is not None:
            # VoiceAttack branch only: ``match`` is known here (F10 leaves it ``None`` and the
            # learner treats that as no signal), and the snap near-misses are the candidate
            # phrases. Best-effort — the learner swallows its own errors and never affects
            # dispatch. A confirmed not-matched / snap-abstained outcome yields a proposal
            # (propose-only by default; auto-apply writes a LEARNED mapping, ADR-0006).
            learn_from_outcome.execute(result, snap, match)

    telemetry.record(
        ReconciliationOutcome(
            raw_text=result.raw_text,
            cleaned_text=result.cleaned_text,
            command_text=result.command_text,
            sent_text=sent_text,
            destination=destination,
            match=match,
            snap=_snap_summary(snap),
            resolution=_resolution_summary(resolution),
            dispatch=dispatch,
        )
    )
    return RouteOutcome(
        destination=destination,
        sent_text=sent_text,
        snap=snap,
        match=match,
        resolution=resolution,
        dispatch=dispatch,
    )


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
        vocabulary: ReconciliationVocabulary,
        surface_matcher: CommandSurfaceMatcher,
        snapper: PhraseMatcher,
        command_dispatcher: CommandDispatcher,
        kneeboard_sink: KneeboardSink,
        telemetry: TelemetrySink,
        reporter: StatusReporter,
        repository: VocabularyRepository,
        clock: Clock,
        learn_from_outcome: LearnFromOutcome | None = None,
    ) -> None:
        """Wire the ports the simulate action routes through (mirrors the PTT flow).

        Args:
            vocabulary: The reconciliation vocabulary port (read live).
            surface_matcher: The command-surface resolver applied before legacy fallback.
            snapper: The phrase matcher applied on the VoiceAttack path.
            command_dispatcher: The typed command dispatcher.
            kneeboard_sink: The DCS kneeboard sink.
            telemetry: The telemetry sink the outcome is recorded to.
            reporter: The status reporter (surfaces the agent-triggered dispatch).
            repository: The vocabulary repository stamped with usage on a match (ADR-0006).
            clock: The clock supplying the usage-stamp time.
            learn_from_outcome: The vocabulary learning use case (ADR-0006), or ``None`` to
                disable learning. Routed through the shared ``route_command`` so simulate
                learns identically to the PTT flow (VoiceAttack branch only).
        """
        self._vocabulary = vocabulary
        self._surface_matcher = surface_matcher
        self._snapper = snapper
        self._command_dispatcher = command_dispatcher
        self._kneeboard_sink = kneeboard_sink
        self._telemetry = telemetry
        self._reporter = reporter
        self._repository = repository
        self._clock = clock
        self._learn_from_outcome = learn_from_outcome

    def execute(self, text: str) -> RouteOutcome:
        """Reconcile ``text`` and dispatch it for real, returning the route outcome.

        Args:
            text: The utterance text to simulate (as if it had been transcribed).

        Returns:
            The :class:`RouteOutcome` for the dispatched command.
        """
        result = reconcile(
            text,
            self._vocabulary.get_word_mappings(),
            self._vocabulary.get_fuzzy_words(),
            PHONETIC_ALPHABET,
            _FUZZY_THRESHOLD,
            _FUZZY_THRESHOLD,
        )
        outcome = route_command(
            result,
            surface_matcher=self._surface_matcher,
            snapper=self._snapper,
            command_dispatcher=self._command_dispatcher,
            kneeboard_sink=self._kneeboard_sink,
            telemetry=self._telemetry,
            repository=self._repository,
            clock=self._clock,
            reporter=self._reporter,
            learn_from_outcome=self._learn_from_outcome,
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
    from the structured vocabulary projection and emits no per-edit provenance, so attribution is
    approximated by *surface form* — a repository entry (seeded by
    same vocabulary source) is credited when one of its
    canonical ``term`` tokens appears in the matched command. This can over-credit a term the
    speaker simply uttered, but for an LRU recency signal that is the safe error direction (a
    useful term is kept, not decayed); a positive match never *under*-credits a term that did
    fire. Precise per-edit provenance (Tier 1 by exact edit, Tier 2 counterfactual) remains
    a later pipeline enhancement. A repository with no seeded entries is a clean no-op.

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


def _resolution_summary(
    resolution: CommandResolution | None,
) -> CommandResolutionSummary | None:
    """Flatten command-surface resolution into the telemetry record."""
    if resolution is None:
        return None
    surface = resolution.surface
    return CommandResolutionSummary(
        decision=str(resolution.decision),
        surface_id=None if surface is None else surface.id,
        label=None if surface is None else surface.label,
        source=None if surface is None else surface.source,
        target_kind=None if surface is None else surface.dispatch_target.target_kind.value,
        matched_alias=resolution.matched_alias,
        score=resolution.score,
        reason_code=resolution.reason_code,
        reason=resolution.reason,
        menu_path=(
            resolution.surface.dispatch_target.menu_path
            if resolution.surface is not None
            and isinstance(resolution.surface.dispatch_target, VaicomF10Action)
            else ()
        ),
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


def _report_snap_diagnostics(
    command: str,
    snap: SnapResult,
    reporter: StatusReporter | None,
) -> None:
    """Surface the phrase snapper's decision in the UI alongside telemetry."""
    if reporter is None:
        return

    if snap.candidate is None:
        reporter.report("Phrase snap: raw (no phrase index loaded)", StatusLevel.DETAIL)
        return

    score = _format_score(snap.score)
    if snap.decision is SnapDecision.SNAPPED:
        if snap.text == command:
            reporter.report(
                f"Phrase snap: exact match '{snap.text}' (score {score})",
                StatusLevel.DETAIL,
            )
        else:
            reporter.report(
                f"Phrase snap: snapped to '{snap.text}' (score {score})",
                StatusLevel.SUCCESS,
            )
        return

    if snap.decision is SnapDecision.ABSTAINED:
        reporter.report(
            f"Phrase snap: abstained; best '{snap.candidate}' (score {score})",
            StatusLevel.WARNING,
        )
        if snap.near_misses:
            reporter.report(
                f"Near misses: {_format_near_misses(snap.near_misses)}",
                StatusLevel.WARNING,
            )
        return

    reporter.report(
        f"Phrase snap: raw; best '{snap.candidate}' (score {score})",
        StatusLevel.DETAIL,
    )


def _report_resolution_diagnostics(
    command: str,
    resolution: CommandResolution,
    reporter: StatusReporter | None,
) -> None:
    """Surface the command-surface resolver decision in the UI."""
    if reporter is None:
        return

    surface = resolution.surface
    if resolution.decision is CommandResolutionDecision.RESOLVED and surface is not None:
        score = _format_score(resolution.score)
        if resolution.matched_alias == command:
            reporter.report(
                f"Command surface: exact '{surface.label}' ({surface.source}, score {score})",
                StatusLevel.DETAIL,
            )
        else:
            reporter.report(
                f"Command surface: resolved '{surface.label}' ({surface.source}, score {score})",
                StatusLevel.SUCCESS,
            )
        return

    if resolution.decision is CommandResolutionDecision.ABSTAINED and surface is not None:
        reporter.report(
            f"Command surface: abstained; best '{surface.label}' "
            f"({_format_score(resolution.score)})",
            StatusLevel.WARNING,
        )
        return

    if resolution.decision is CommandResolutionDecision.REJECTED:
        reporter.report(
            f"Command surface: rejected ({resolution.reason or 'unsupported command'})",
            StatusLevel.WARNING,
        )
        return

    reporter.report("Command surface: raw fallback", StatusLevel.DETAIL)


def _report_dispatch_rejection(
    dispatch: DispatchOutcome,
    reporter: StatusReporter | None,
) -> None:
    """Surface an adapter refusing to execute a typed dispatch target."""
    if reporter is None:
        return
    detail = f": {dispatch.detail}" if dispatch.detail else ""
    reporter.report(
        f"Dispatch not accepted for {dispatch.target_kind}{detail}",
        StatusLevel.WARNING,
    )


def _format_near_misses(near_misses: tuple[NearMiss, ...]) -> str:
    """Format near-miss candidates for one compact status line."""
    return "; ".join(
        f"{near_miss.phrase} {_format_score(near_miss.score)}" for near_miss in near_misses
    )


def _format_score(score: float) -> str:
    """Format a snap score for human-readable status output."""
    return f"{score:.1f}"
