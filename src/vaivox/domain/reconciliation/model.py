"""Value objects produced by the reconciliation pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReconciliationResult:
    """The staged result of reconciling one raw transcript into a command.

    Attributes:
        raw_text: The transcript exactly as returned by the STT provider.
        cleaned_text: The transcript after deterministic cleanup (no fuzzy step).
        command_text: The cleaned text after fuzzy correction; the command sent on.
    """

    raw_text: str
    cleaned_text: str
    command_text: str
