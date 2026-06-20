"""Driven ports: the interfaces the use cases depend on (ADR-0001).

These are the only surface the application layer knows about the outside world.
Concrete adapters live in :mod:`vaivox.infrastructure` and are wired by the
composition root. Ports are :class:`typing.Protocol` types so adapters conform
*structurally* — no base class to import inward — and so fakes in tests need only
match the shape.

The dependency rule (enforced by import-linter) keeps this module free of any
infrastructure import.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from vaivox.domain.commands.model import (
    CommandResolution,
    CommandSurface,
    DispatchOutcome,
    DispatchTarget,
    VaicomF10Action,
)
from vaivox.domain.reconciliation.model import Transcription
from vaivox.domain.reconciliation.snapper import SnapResult
from vaivox.domain.telemetry.model import MatchOutcome, ReconciliationOutcome
from vaivox.domain.vocabulary.model import GovernedEntry, VocabularyEntry, VocabularyKind


class SpeechToTextError(Exception):
    """Raised when a speech-to-text provider cannot load or transcribe audio.

    Adapters raise this (never a provider-specific exception) so the use cases can
    handle every backend uniformly.
    """


@runtime_checkable
class SpeechToText(Protocol):
    """Driven port: turn recorded audio into a normalized transcript."""

    def load(self) -> None:
        """Prepare the provider for transcription (validate keys, load models)."""

    def transcribe(self, audio_path: str) -> Transcription:
        """Transcribe the audio file at ``audio_path`` into a :class:`Transcription`."""


@runtime_checkable
class AudioRecorder(Protocol):
    """Driven port: capture push-to-talk microphone audio to a file."""

    @property
    def is_recording(self) -> bool:
        """Whether a recording is currently in progress."""

    def start(self) -> None:
        """Begin capturing audio to the recorder's output file."""

    def stop(self) -> str | None:
        """Stop capturing and return the recorded file path, or ``None`` if empty."""


@runtime_checkable
class CommandSink(Protocol):
    """Driven port: dispatch a static command phrase to VoiceAttack.

    New routing code should prefer :class:`CommandDispatcher`, which accepts typed
    dispatch targets and delegates this exact-name path only for
    :class:`~vaivox.domain.commands.model.VoiceAttackCommand`. Live VAICOM F10 actions take
    the separate :class:`VaicomF10ActionSink` path (ADR-0012) — they are *not* VoiceAttack
    commands, so they would never match here.
    """

    def send(self, command: str) -> MatchOutcome | None:
        """Send ``command`` to VoiceAttack and return its match outcome (ADR-0006).

        The dispatch is synchronous request/response on one connection: the adapter sends
        the command, then reads the plugin's reply back on the *same* socket.

        Returns:
            The :class:`~vaivox.domain.telemetry.model.MatchOutcome` the plugin reported,
            or ``None`` when the outcome is **unknown** — no reply (a pre-return-channel
            plugin that closes the socket), a read timeout, or a malformed reply. A
            ``None`` outcome is recorded as unknown telemetry and never stamps vocabulary
            usage, so the routing flow degrades cleanly against an un-rebuilt plugin.
        """


@dataclass(frozen=True)
class CommandDispatchResult:
    """The result of dispatching a typed command target.

    Attributes:
        dispatch: Adapter-level dispatch result for telemetry and diagnostics.
        match: VoiceAttack's exact-name match result for a static
            :class:`~vaivox.domain.commands.model.VoiceAttackCommand` (ADR-0006); ``None``
            for a VAICOM F10 action (the UDP ``doAction`` path is fire-and-forget, with no
            return channel) or when the plugin reply is unavailable.
    """

    dispatch: DispatchOutcome
    match: MatchOutcome | None = None


@runtime_checkable
class CommandDispatcher(Protocol):
    """Driven port: dispatch a typed command target."""

    def dispatch(self, target: DispatchTarget) -> CommandDispatchResult:
        """Dispatch ``target`` through the adapter matching its target kind."""


@runtime_checkable
class VaicomF10ActionSink(Protocol):
    """Driven port: fire a live VAICOM-imported DCS F10 action (ADR-0012).

    Mission F10 items are *not* VoiceAttack commands; VAICOM fires them by sending DCS a
    ``mission.player.actionsequence`` datagram carrying the menu item's ``ActionIndex``,
    which DCS runs via ``missionCommands.doAction`` (a single index fires any item, nesting
    included). The adapter replicates exactly that datagram. It is fire-and-forget — DCS
    sends no acknowledgement — so the result is a :class:`DispatchOutcome` only (no
    :class:`MatchOutcome`).
    """

    def dispatch(self, action: VaicomF10Action) -> DispatchOutcome:
        """Fire ``action`` via DCS ``doAction``, or report why it could not be sent."""


@runtime_checkable
class CommandSurfaceMatcher(Protocol):
    """Driven port: resolve reconciled text to a typed command surface."""

    def resolve(self, text: str) -> CommandResolution:
        """Resolve ``text`` to a command surface, or abstain/raw."""


@runtime_checkable
class KneeboardSink(Protocol):
    """Driven port: write a free-text note to the DCS kneeboard."""

    def send(self, note_text: str) -> None:
        """Format and deliver ``note_text`` to the in-game kneeboard."""


@runtime_checkable
class PhraseMatcher(Protocol):
    """Driven port: snap a reconciled command to a valid command phrase (ADR-0011).

    The use case calls :meth:`snap` once per VoiceAttack-bound utterance. The domain
    :class:`~vaivox.domain.reconciliation.snapper.PhraseSnapper` satisfies this directly
    (a frozen index); the infrastructure reloadable adapter
    (:class:`~vaivox.infrastructure.reload.phrase_snapper.ReloadablePhraseSnapper`)
    satisfies it too, swapping a regenerated index in at idle (ADR-0009) behind the same
    method — so the application never knows whether the index is frozen or hot-reloadable.
    """

    def snap(self, text: str) -> SnapResult:
        """Score ``text`` against the phrase index and decide snap / abstain / raw."""


class StatusLevel(Enum):
    """Semantic severity of a user-facing status line.

    The UI adapter maps each level to a colour; headless adapters may map it to a
    log level. The application never names colours directly.
    """

    INFO = "info"
    DETAIL = "detail"
    TRANSCRIPT = "transcript"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@runtime_checkable
class StatusReporter(Protocol):
    """Driven port: surface human-readable status to the user."""

    def report(self, message: str, level: StatusLevel = StatusLevel.INFO) -> None:
        """Report ``message`` at the given semantic ``level``."""


@runtime_checkable
class TelemetrySink(Protocol):
    """Driven port: persist a reconciliation outcome for later analysis (ADR-0006)."""

    def record(self, outcome: ReconciliationOutcome) -> None:
        """Record one :class:`ReconciliationOutcome`."""


@runtime_checkable
class TelemetryReader(Protocol):
    """Driven port: read back recorded reconciliation outcomes (ADR-0010).

    The read counterpart of :class:`TelemetrySink`, powering the introspection API's
    recent-events and live-metrics queries. It returns reconstructed domain value
    objects (not raw rows) so query use cases can introspect typed fields; the adapter
    degrades gracefully (an absent or malformed store yields an empty list, never an
    exception into a read-only query).
    """

    def recent(self, limit: int) -> list[ReconciliationOutcome]:
        """Return up to ``limit`` most recent outcomes, oldest first.

        Args:
            limit: The maximum number of outcomes to return (most recent retained). A
                non-positive limit yields an empty list.

        Returns:
            The reconstructed outcomes in recording order (oldest first), at most
            ``limit`` long; empty when nothing has been recorded yet.
        """


@runtime_checkable
class VocabularyRepository(Protocol):
    """Driven port: the structured-vocabulary store (ADR-0004, Axis A).

    The repository is the single source of truth the reconciliation pipeline reads
    (ADR-0009). It joins the versioned JSONL *source* with the hot usage *sidecar* and
    exposes the joined view; mutations (usage stamps, eviction) flow back through it.
    Adapters live in :mod:`vaivox.infrastructure.vocabulary`.
    """

    def load(self, kind: VocabularyKind) -> list[GovernedEntry]:
        """Return every entry of ``kind``, each joined with its usage stats."""

    def mark_used(self, ids: Sequence[str], when: datetime) -> None:
        """Stamp ``last_used`` / increment ``hits`` for the contributing entry ``ids``.

        Called only on a matched utterance, for the entries Tier 1/2 attribution
        credited (ADR-0006 §2). Unknown ids are ignored.
        """

    def add(self, entry: VocabularyEntry, when: datetime) -> None:
        """Add a new source ``entry`` and seed its usage (``last_used = when``).

        Seeding recency to ``when`` keeps a brand-new entry out of immediate eviction
        (the grace window, ADR-0004 §3).
        """

    def replace_entries(self, kind: VocabularyKind, kept: Sequence[GovernedEntry]) -> None:
        """Persist the post-eviction ``kept`` set for ``kind`` (drops the rest).

        The write-back of a :class:`~vaivox.domain.vocabulary.model.EvictionResult`'s
        ``kept`` entries after a governance pass.
        """


@runtime_checkable
class ReconciliationVocabulary(Protocol):
    """Driven port: read the effective vocabulary used by reconciliation.

    This keeps the runtime command pipeline on structured vocabulary while preserving the
    domain pipeline's compact legacy-shaped inputs: alias-to-replacement word mappings and
    fuzzy-correction terms.
    """

    def get_word_mappings(self) -> Mapping[str, str]:
        """Return the effective alias-to-replacement word mappings."""

    def get_fuzzy_words(self) -> Sequence[str]:
        """Return the candidate words for fuzzy correction."""


@dataclass(frozen=True)
class VocabularyGenerationResult:
    """The outcome of a VAICOM vocabulary generation attempt (ADR-0005).

    Attributes:
        generated: Whether generation actually ran and wrote the keyterm + phrase-index
            files (``False`` when no VAICOM install was found or the generator was
            unavailable — the generic seed remains in use).
        reason: A short human-readable status (e.g. ``"generated"``, ``"no VAICOM install
            found"``), surfaced to the user and the logs.
        keyterm_count: How many keyterms were written (``0`` when nothing was generated).
        phrase_count: How many command phrases were written to the snap index.
        source: The discovered VAICOM install root used, or ``None`` when none was found.
    """

    generated: bool
    reason: str
    keyterm_count: int = 0
    phrase_count: int = 0
    source: str | None = None


@dataclass(frozen=True)
class MissionVocabularyDiagnostics:
    """Verbose detail of one mission F10 pull (surfaced when verbose logging is enabled).

    Attributes:
        log_path: The log path the adapter resolved and tried to read, if any.
        file_bytes: Size of the read log in bytes (0 when missing/unreadable).
        mission_markers: Number of ``Mission title:`` markers found in the log.
        latest_mission: The latest mission title the overlay scoped to, if any.
        scoped_matches: F10 command matches within the latest-mission scope.
        whole_log_matches: Historical ``Set menu F10 item`` matches across the log.
        fallback_used: Whether a marker-free legacy log required whole-file parsing.
        deduped_phrases: Final command count after de-duplication and the safety cap.
    """

    log_path: str | None = None
    file_bytes: int = 0
    mission_markers: int = 0
    latest_mission: str | None = None
    scoped_matches: int = 0
    whole_log_matches: int = 0
    fallback_used: bool = False
    deduped_phrases: int = 0


@dataclass(frozen=True)
class MissionVocabularySnapshot:
    """Ephemeral mission-scoped vocabulary discovered from the live simulator session.

    Attributes:
        phrases: The current mission-only command phrases. They are intentionally not
            persisted in the structured vocabulary source because they expire with the
            mission/server context.
        surfaces: The current mission-only command surfaces, preserving VAICOM's
            internal F10 identifier and dispatch metadata for typed routing.
        source: Human-readable source location used to discover the phrases, if any.
        reason: Short status suitable for logs and diagnostics.
        diagnostics: Optional verbose pull detail for the diagnostic log, if computed.
    """

    phrases: tuple[str, ...]
    surfaces: tuple[CommandSurface, ...] = ()
    source: str | None = None
    reason: str = "loaded"
    diagnostics: MissionVocabularyDiagnostics | None = None


@runtime_checkable
class MissionVocabularySource(Protocol):
    """Driven port: read mission-scoped dynamic command phrases."""

    def load(self) -> MissionVocabularySnapshot:
        """Return the current mission-only dynamic command phrases."""


@runtime_checkable
class VocabularyGenerator(Protocol):
    """Driven port: (re)generate the VAICOM-derived vocabulary into the data dir (ADR-0005).

    VAICOM-derived data is never shipped (ADR-0005); it is generated locally from the
    user's own install on first run / when stale. The concrete adapter wraps
    ``vaivox.infrastructure.vocabulary.vaicom_generator_core`` (auto-discovery + parsing); the
    :class:`~vaivox.application.refresh_vocabulary.RefreshVocabulary` use case drives it
    on a background thread and hot-applies the regenerated phrase index (ADR-0009).
    """

    def is_stale(self) -> bool:
        """Whether the generated vocabulary is missing or out of date (worth regenerating).

        Returns:
            ``True`` when the output files are absent, or a discoverable install's sources
            are newer than them; ``False`` when up to date or nothing can be regenerated.
        """

    def generate(self) -> VocabularyGenerationResult:
        """Discover the VAICOM install and write keyterms + the phrase index.

        Returns:
            A :class:`VocabularyGenerationResult`; ``generated=False`` (never raised) when
            no install is found or the generator is unavailable, so a background caller
            degrades gracefully to the generic seed.
        """


@runtime_checkable
class Clock(Protocol):
    """Driven port: read the current time (injected so timing is testable)."""

    def now(self) -> datetime:
        """Return the current wall-clock time."""


@runtime_checkable
class ConfigProvider(Protocol):
    """Driven port: read effective configuration the use cases need at runtime."""

    def get_safe_configuration(self) -> Mapping[str, str]:
        """Return the effective configuration with secrets redacted."""

    def get_stt_backend(self) -> str:
        """Return the configured speech-to-text backend name."""
