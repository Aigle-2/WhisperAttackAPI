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
