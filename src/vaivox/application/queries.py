"""Read-only query use cases behind the introspection API (ADR-0010).

These power the localhost introspection adapter so agents (and humans) can inspect
runtime state and reproduce a reconciliation without a mic or VoiceAttack. They go
*through* the same ports as the app — no domain bypass — and never expose secrets
(the status query reuses the redacted-config accessor).
"""

from __future__ import annotations

from dataclasses import dataclass

from vaivox import __version__
from vaivox.application.ports import AudioRecorder, ConfigProvider
from vaivox.domain.reconciliation.model import ReconciliationResult
from vaivox.domain.reconciliation.pipeline import reconcile
from vaivox.domain.vocabulary.keyterms import PHONETIC_ALPHABET

_FUZZY_THRESHOLD = 85


@dataclass(frozen=True)
class StatusReport:
    """A snapshot of runtime status for the introspection API.

    Attributes:
        version: The application version.
        recording: Whether a recording is currently in progress.
        stt_backend: The configured speech-to-text backend name.
        config: The effective configuration with secrets redacted.
    """

    version: str
    recording: bool
    stt_backend: str
    config: dict[str, str]


class DescribeStatus:
    """Report the current runtime status (read-only)."""

    def __init__(self, recorder: AudioRecorder, config: ConfigProvider) -> None:
        """Wire the recorder and configuration provider.

        Args:
            recorder: The audio recorder port (for the recording flag).
            config: The configuration provider port.
        """
        self._recorder = recorder
        self._config = config

    def execute(self) -> StatusReport:
        """Return a :class:`StatusReport` snapshot."""
        return StatusReport(
            version=__version__,
            recording=self._recorder.is_recording,
            stt_backend=self._config.get_stt_backend(),
            config=dict(self._config.get_safe_configuration()),
        )


class DryRunReconcile:
    """Run text through the full reconciliation pipeline without any I/O."""

    def __init__(self, config: ConfigProvider) -> None:
        """Wire the configuration provider (read live for word mappings/fuzzy words).

        Args:
            config: The configuration provider port.
        """
        self._config = config

    def execute(self, text: str) -> ReconciliationResult:
        """Reconcile ``text`` and return the staged transformations.

        Args:
            text: The raw transcript to reconcile.

        Returns:
            The staged raw -> cleaned -> command result.
        """
        return reconcile(
            text,
            self._config.get_word_mappings(),
            self._config.get_fuzzy_words(),
            PHONETIC_ALPHABET,
            _FUZZY_THRESHOLD,
            _FUZZY_THRESHOLD,
        )
