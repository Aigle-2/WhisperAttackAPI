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
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from vaivox.domain.reconciliation.model import Transcription
from vaivox.domain.telemetry.model import ReconciliationOutcome
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
    """Driven port: dispatch a recognized command to VoiceAttack."""

    def send(self, command: str) -> None:
        """Send ``command`` to VoiceAttack for matching and dispatch."""


@runtime_checkable
class KneeboardSink(Protocol):
    """Driven port: write a free-text note to the DCS kneeboard."""

    def send(self, note_text: str) -> None:
        """Format and deliver ``note_text`` to the in-game kneeboard."""


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
class Clock(Protocol):
    """Driven port: read the current time (injected so timing is testable)."""

    def now(self) -> datetime:
        """Return the current wall-clock time."""


@runtime_checkable
class ConfigProvider(Protocol):
    """Driven port: read effective configuration the use cases need at runtime.

    Read live (not snapshotted) because word mappings can be added while the app
    runs, mirroring the legacy behaviour.
    """

    def get_word_mappings(self) -> Mapping[str, str]:
        """Return the effective alias-to-replacement word mappings."""

    def get_fuzzy_words(self) -> Sequence[str]:
        """Return the candidate words for fuzzy correction."""

    def get_safe_configuration(self) -> Mapping[str, str]:
        """Return the effective configuration with secrets redacted."""

    def get_stt_backend(self) -> str:
        """Return the configured speech-to-text backend name."""
