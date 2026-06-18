"""Telemetry value objects emitted through the ``TelemetrySink`` port (ADR-0006).

These are plain, immutable value objects — not an event-sourcing system (ADR-0001).
The application layer builds one :class:`ReconciliationOutcome` per utterance and
fans it out through driven ports; the JSONL sink and near-miss capture are enriched
in Phase 5.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchOutcome:
    """The result of VoiceAttack's match attempt for a dispatched command.

    Returned by the plugin's synchronous reply channel (ADR-0006). Until the plugin
    reply is wired in Phase 5 the sink reports ``None`` (unknown), which telemetry
    records without stamping vocabulary usage.

    Attributes:
        matched: Whether VoiceAttack found and dispatched a command for the text.
        resolved_command: The command VoiceAttack resolved to, when matched.
    """

    matched: bool
    resolved_command: str | None = None


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
    """

    raw_text: str
    cleaned_text: str
    command_text: str
    sent_text: str
    destination: str
    match: MatchOutcome | None = None
