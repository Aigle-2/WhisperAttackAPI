"""Read-only query use cases behind the introspection API (ADR-0010).

These power the localhost introspection adapter so agents (and humans) can inspect
runtime state and reproduce a reconciliation without a mic or VoiceAttack. They go
*through* the same ports as the app — no domain bypass — and never expose secrets
(the status query reuses the redacted-config accessor).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vaivox import __version__
from vaivox.application.ports import (
    AudioRecorder,
    ConfigProvider,
    ReconciliationVocabulary,
    TelemetryReader,
    VocabularyRepository,
)
from vaivox.domain.reconciliation.model import ReconciliationResult
from vaivox.domain.reconciliation.pipeline import reconcile
from vaivox.domain.telemetry.model import MatchOutcome, ReconciliationOutcome
from vaivox.domain.vocabulary.keyterms import PHONETIC_ALPHABET
from vaivox.domain.vocabulary.model import VocabularyKind

_FUZZY_THRESHOLD = 85

DEFAULT_RECENT_LIMIT = 20


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

    def __init__(self, vocabulary: ReconciliationVocabulary) -> None:
        """Wire the reconciliation vocabulary provider.

        Args:
            vocabulary: The reconciliation vocabulary port.
        """
        self._vocabulary = vocabulary

    def execute(self, text: str) -> ReconciliationResult:
        """Reconcile ``text`` and return the staged transformations.

        Args:
            text: The raw transcript to reconcile.

        Returns:
            The staged raw -> cleaned -> command result.
        """
        return reconcile(
            text,
            self._vocabulary.get_word_mappings(),
            self._vocabulary.get_fuzzy_words(),
            PHONETIC_ALPHABET,
            _FUZZY_THRESHOLD,
            _FUZZY_THRESHOLD,
        )


@dataclass(frozen=True)
class RecentReconciliations:
    """The most recent recorded reconciliation outcomes (read-only, ADR-0010).

    Attributes:
        limit: The cap applied when reading (the requested number of events).
        count: How many events were actually returned (``<= limit``).
        events: The outcomes, oldest first, each the full raw -> sent provenance.
    """

    limit: int
    count: int
    events: tuple[ReconciliationOutcome, ...] = ()


class ListRecentReconciliations:
    """Return the most recent reconciliation outcomes from the telemetry log."""

    def __init__(self, telemetry: TelemetryReader) -> None:
        """Wire the telemetry reader port.

        Args:
            telemetry: The telemetry reader port (the JSONL reader in production).
        """
        self._telemetry = telemetry

    def execute(self, limit: int = DEFAULT_RECENT_LIMIT) -> RecentReconciliations:
        """Return up to ``limit`` recent outcomes (oldest first).

        Args:
            limit: The maximum number of events to return.

        Returns:
            A :class:`RecentReconciliations` snapshot.
        """
        events = tuple(self._telemetry.recent(limit))
        return RecentReconciliations(limit=limit, count=len(events), events=events)


@dataclass(frozen=True)
class LiveMetrics:
    """Aggregate reconciliation health computed from recorded telemetry (ADR-0010).

    Mirrors the offline eval's bands (ADR-0008) but is computed from real recorded
    outcomes rather than a golden dataset. A band is derived per event:

    - ``match`` / ``wrong_match`` / ``not_found`` come from the downstream
      :class:`~vaivox.domain.telemetry.model.MatchOutcome` once the plugin return
      channel is wired (ADR-0006); ``unknown`` counts events whose match outcome was
      never reported (the current default, ``match is None``).
    - ``abstain`` counts events the phrase snapper held back (its decision was
      ``"abstained"``), independent of the match outcome.

    Rates are over ``total`` (0.0 when there are no events).

    Attributes:
        total: The number of events aggregated.
        match: Events VoiceAttack matched to the expected command.
        wrong_match: Events VoiceAttack matched to a different command.
        not_found: Events VoiceAttack reported no match for.
        unknown: Events whose match outcome was never reported (no return channel).
        abstain: Events the snapper abstained on (a held-back near-miss).
        match_rate: ``match / total``.
        wrong_match_rate: ``wrong_match / total``.
        not_found_rate: ``not_found / total``.
        abstain_rate: ``abstain / total``.
    """

    total: int = 0
    match: int = 0
    wrong_match: int = 0
    not_found: int = 0
    unknown: int = 0
    abstain: int = 0
    match_rate: float = 0.0
    wrong_match_rate: float = 0.0
    not_found_rate: float = 0.0
    abstain_rate: float = 0.0


_METRICS_WINDOW = 1000


class ComputeMetrics:
    """Aggregate recorded reconciliation outcomes into live health metrics."""

    def __init__(self, telemetry: TelemetryReader) -> None:
        """Wire the telemetry reader port.

        Args:
            telemetry: The telemetry reader port (the JSONL reader in production).
        """
        self._telemetry = telemetry

    def execute(self, window: int = _METRICS_WINDOW) -> LiveMetrics:
        """Aggregate the most recent ``window`` outcomes into :class:`LiveMetrics`.

        Args:
            window: How many recent events to aggregate over.

        Returns:
            The computed :class:`LiveMetrics`.
        """
        events = self._telemetry.recent(window)
        total = len(events)
        match = wrong_match = not_found = unknown = abstain = 0
        for event in events:
            if event.snap is not None and event.snap.decision == "abstained":
                abstain += 1
            outcome = event.match
            if outcome is None:
                unknown += 1
            elif not outcome.matched:
                not_found += 1
            elif _is_expected_match(event, outcome):
                match += 1
            else:
                wrong_match += 1

        def rate(count: int) -> float:
            return round(count / total, 4) if total else 0.0

        return LiveMetrics(
            total=total,
            match=match,
            wrong_match=wrong_match,
            not_found=not_found,
            unknown=unknown,
            abstain=abstain,
            match_rate=rate(match),
            wrong_match_rate=rate(wrong_match),
            not_found_rate=rate(not_found),
            abstain_rate=rate(abstain),
        )


def _is_expected_match(event: ReconciliationOutcome, outcome: MatchOutcome) -> bool:
    """Whether a matched event resolved to the command we dispatched (vs. a wrong one).

    The eval distinguishes ``match`` from ``wrong_match`` against a golden expectation
    (ADR-0008). At runtime there is no oracle, so the dispatched ``sent_text`` is the
    expectation: a matched command that VoiceAttack resolved to a *different* command is
    a wrong match. When the plugin does not report which command it resolved, a positive
    match is trusted as a true match.

    Args:
        event: The recorded outcome (its ``sent_text`` is the dispatched command).
        outcome: The downstream match outcome (``matched`` is already known true).

    Returns:
        ``True`` for a true match, ``False`` for a wrong match.
    """
    if outcome.resolved_command is None:
        return True
    return _normalize(outcome.resolved_command) == _normalize(event.sent_text)


def _normalize(text: str) -> str:
    """Casefold and collapse whitespace for a forgiving command comparison."""
    return " ".join(text.split()).casefold()


@dataclass(frozen=True)
class VocabularyTermView:
    """One vocabulary entry joined with its usage stats, flattened for the API.

    Attributes:
        id: The stable entry id.
        kind: The vocabulary kind value (``"fuzzy_word"`` / ``"word_mapping"`` /
            ``"alias"``).
        term: The canonical term.
        aliases: Alternate surface forms that resolve to ``term``.
        origin: ``"default"`` (protected) or ``"learned"`` (evictable).
        hits: How many matches the entry has contributed to.
        last_used: ISO-8601 timestamp of the entry's last use (epoch when never used).
    """

    id: str
    kind: str
    term: str
    aliases: tuple[str, ...]
    origin: str
    hits: int
    last_used: str


@dataclass(frozen=True)
class VocabularyReport:
    """The loaded vocabulary entries plus usage stats, grouped by kind (ADR-0010).

    Attributes:
        total: The total number of entries across all kinds.
        by_kind: A ``kind -> [entries]`` mapping for every vocabulary kind, each list
            ordered most-recently-used first.
    """

    total: int = 0
    by_kind: dict[str, list[VocabularyTermView]] = field(default_factory=dict)


class DescribeVocabulary:
    """Report the loaded vocabulary entries and their usage stats across all kinds."""

    def __init__(self, repository: VocabularyRepository) -> None:
        """Wire the vocabulary repository port.

        Args:
            repository: The vocabulary repository port (the JSONL repo in production).
        """
        self._repository = repository

    def execute(self) -> VocabularyReport:
        """Load every vocabulary kind and flatten it into a :class:`VocabularyReport`.

        Returns:
            The grouped vocabulary view; entries are ordered most-recently-used first
            within each kind.
        """
        by_kind: dict[str, list[VocabularyTermView]] = {}
        total = 0
        for kind in VocabularyKind:
            governed = self._repository.load(kind)
            governed.sort(key=lambda entry: entry.usage.last_used, reverse=True)
            by_kind[kind.value] = [
                VocabularyTermView(
                    id=entry.id,
                    kind=entry.entry.kind.value,
                    term=entry.entry.term,
                    aliases=entry.entry.aliases,
                    origin=entry.entry.origin.value,
                    hits=entry.usage.hits,
                    last_used=entry.usage.last_used.isoformat(),
                )
                for entry in governed
            ]
            total += len(governed)
        return VocabularyReport(total=total, by_kind=by_kind)
