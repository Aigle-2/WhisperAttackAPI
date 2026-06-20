"""Telemetry value objects emitted through the ``TelemetrySink`` port (ADR-0006).

These are plain, immutable value objects — not an event-sourcing system (ADR-0001).
The application layer builds one :class:`ReconciliationOutcome` per utterance and
fans it out through driven ports; the JSONL sink and near-miss capture are enriched
in Phase 5.
"""

from __future__ import annotations

from dataclasses import dataclass

from vaivox.domain.commands.model import DispatchOutcome


@dataclass(frozen=True)
class MatchOutcome:
    """The result of VoiceAttack's match attempt for a dispatched command.

    Returned by the plugin's synchronous reply channel (ADR-0006): the command sink
    reads one JSON line back on the same socket right after dispatch and parses it into
    this value object. A ``None`` outcome (not an instance of this class) means the
    result is *unknown* — no reply at all (a pre-return-channel plugin), a read timeout,
    or a malformed reply — which telemetry records without stamping vocabulary usage. A
    populated outcome with ``matched`` true stamps usage on the credited entries
    (ADR-0004 attribution).

    Attributes:
        matched: Whether VoiceAttack found and dispatched a command for the text.
        resolved_command: The submitted VoiceAttack profile phrase when matched; ``None``
            otherwise.
    """

    matched: bool
    resolved_command: str | None = None


@dataclass(frozen=True)
class SnapSummary:
    """The phrase-snapper's decision for one utterance (Axis B, ADR-0011).

    A flat, serializable summary of the snap step recorded in the telemetry outcome.
    It is deliberately decoupled from the reconciliation
    :class:`~vaivox.domain.reconciliation.snapper.SnapResult` so the telemetry record
    schema stays stable as the snapper evolves.

    Attributes:
        decision: Which band the candidate fell into (``"snapped"`` / ``"abstained"``
            / ``"raw"``).
        candidate: The best-scoring phrase considered, or ``None`` for an empty index.
        score: The best candidate's score (0-100), or ``0.0`` for an empty index.
        near_misses: The abstain-band near-miss candidates as ``(phrase, score)``
            pairs; empty unless the snapper abstained.
    """

    decision: str
    candidate: str | None = None
    score: float = 0.0
    near_misses: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class CommandResolutionSummary:
    """The command-surface resolver's decision for one utterance.

    This is a telemetry-facing projection of a
    :class:`~vaivox.domain.commands.model.CommandResolution`: it records the resolved
    surface and target kind without embedding the whole command catalog entry.

    Attributes:
        decision: ``"resolved"``, ``"abstained"``, or ``"raw"``.
        surface_id: The selected/best surface id, when any candidate was useful.
        label: The selected/best human-facing label.
        source: The surface catalog source (``"voiceattack"`` / ``"mission_f10"``).
        target_kind: The dispatch target kind associated with the surface.
        matched_alias: The alias/label that scored best.
        score: The resolver score (0-100).
    """

    decision: str
    surface_id: str | None = None
    label: str | None = None
    source: str | None = None
    target_kind: str | None = None
    matched_alias: str | None = None
    score: float = 0.0


@dataclass(frozen=True)
class ReconciliationOutcome:
    """The full provenance of one utterance, from raw transcript to dispatch.

    Attributes:
        raw_text: The transcript exactly as returned by the STT provider.
        cleaned_text: The transcript after deterministic cleanup (no fuzzy step).
        command_text: The cleaned text after fuzzy correction.
        sent_text: The text actually dispatched to the destination sink.
        destination: Where the command was routed (``"voiceattack"`` or
            ``"kneeboard"``).
        match: The downstream match outcome, or ``None`` when unknown.
        snap: The phrase-snapper's decision (ADR-0011), or ``None`` when the snapper is
            not wired (preserving the prior record shape).
        resolution: The typed command-surface resolution, when the resolver was wired.
        dispatch: The typed dispatch adapter outcome, when routing dispatched a target.
    """

    raw_text: str
    cleaned_text: str
    command_text: str
    sent_text: str
    destination: str
    match: MatchOutcome | None = None
    snap: SnapSummary | None = None
    resolution: CommandResolutionSummary | None = None
    dispatch: DispatchOutcome | None = None
