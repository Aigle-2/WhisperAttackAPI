"""Read side of the append-only JSONL telemetry log (ADR-0010, over ADR-0006).

The :class:`~vaivox.application.ports.TelemetryReader` adapter. It reads the last N
records the :class:`~vaivox.infrastructure.telemetry.jsonl_sink.JsonlTelemetrySink`
appended to ``telemetry.jsonl`` in the per-user VAIVOX data directory under
%LOCALAPPDATA% and reconstructs each line into a
:class:`~vaivox.domain.telemetry.model.ReconciliationOutcome` (recursing into the
nested :class:`~vaivox.domain.telemetry.model.MatchOutcome` and
:class:`~vaivox.domain.telemetry.model.SnapSummary`).

Reads are best-effort and degrade gracefully (mirroring the other JSONL adapters): a
missing file yields an empty list, and a malformed line is logged and skipped rather
than raised — the read-only introspection queries must never crash on a bad record.

Stdlib only (``json``, ``pathlib``) — no runtime dependency and nothing heavy at
import time, so the package smoke test keeps importing this module cleanly.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path

from vaivox.domain.telemetry.model import MatchOutcome, ReconciliationOutcome, SnapSummary
from vaivox.infrastructure.telemetry.jsonl_sink import TELEMETRY_FILE

_LOGGER = logging.getLogger(__name__)


class JsonlTelemetryReader:
    """Read recent reconciliation outcomes back from the JSONL telemetry log.

    The read counterpart of
    :class:`~vaivox.infrastructure.telemetry.jsonl_sink.JsonlTelemetrySink`; both bind
    to the same ``telemetry.jsonl`` file in the data directory.

    Args:
        data_dir: The per-user VAIVOX data directory the telemetry log lives in.
    """

    def __init__(self, data_dir: str) -> None:
        """Bind the reader to ``data_dir`` (the path is resolved lazily per call)."""
        self._path = Path(data_dir) / TELEMETRY_FILE

    def recent(self, limit: int) -> list[ReconciliationOutcome]:
        """Return up to ``limit`` most recent outcomes, oldest first.

        Args:
            limit: The maximum number of outcomes to return. A non-positive limit
                yields an empty list.

        Returns:
            The reconstructed outcomes in recording order (oldest first), at most
            ``limit`` long; empty when the log is absent, unreadable, or empty.
        """
        if limit <= 0:
            return []
        recent_lines = self._tail_lines(limit)
        outcomes: list[ReconciliationOutcome] = []
        for line in recent_lines:
            outcome = _outcome_from_line(line)
            if outcome is not None:
                outcomes.append(outcome)
        return outcomes

    def _tail_lines(self, limit: int) -> list[str]:
        """Return the last ``limit`` non-empty lines of the log, oldest first."""
        if not self._path.is_file():
            return []
        try:
            with open(self._path, encoding="utf-8") as file:
                tail: deque[str] = deque(
                    (line for raw in file if (line := raw.strip())), maxlen=limit
                )
        except OSError as error:
            _LOGGER.warning("Failed to read telemetry log '%s': %s", self._path, error)
            return []
        return list(tail)


def _outcome_from_line(line: str) -> ReconciliationOutcome | None:
    """Reconstruct one outcome from a JSON line, or ``None`` if the record is malformed."""
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        _LOGGER.warning("Skipping malformed telemetry record: %r", line)
        return None
    if not isinstance(record, dict):
        _LOGGER.warning("Skipping non-object telemetry record: %r", line)
        return None
    raw_text = record.get("raw_text")
    cleaned_text = record.get("cleaned_text")
    command_text = record.get("command_text")
    sent_text = record.get("sent_text")
    destination = record.get("destination")
    if not (
        isinstance(raw_text, str)
        and isinstance(cleaned_text, str)
        and isinstance(command_text, str)
        and isinstance(sent_text, str)
        and isinstance(destination, str)
    ):
        _LOGGER.warning("Skipping telemetry record with missing fields: %r", line)
        return None
    return ReconciliationOutcome(
        raw_text=raw_text,
        cleaned_text=cleaned_text,
        command_text=command_text,
        sent_text=sent_text,
        destination=destination,
        match=_match_from_record(record.get("match")),
        snap=_snap_from_record(record.get("snap")),
    )


def _match_from_record(record: object) -> MatchOutcome | None:
    """Reconstruct the nested match outcome, or ``None`` when unknown/malformed."""
    if not isinstance(record, dict):
        return None
    matched = record.get("matched")
    if not isinstance(matched, bool):
        return None
    resolved = record.get("resolved_command")
    return MatchOutcome(
        matched=matched,
        resolved_command=resolved if isinstance(resolved, str) else None,
    )


def _snap_from_record(record: object) -> SnapSummary | None:
    """Reconstruct the nested snap summary, or ``None`` when absent/malformed."""
    if not isinstance(record, dict):
        return None
    decision = record.get("decision")
    if not isinstance(decision, str):
        return None
    candidate = record.get("candidate")
    raw_score = record.get("score", 0.0)
    score = float(raw_score) if isinstance(raw_score, (int, float)) else 0.0
    return SnapSummary(
        decision=decision,
        candidate=candidate if isinstance(candidate, str) else None,
        score=score,
        near_misses=_near_misses_from_record(record.get("near_misses")),
    )


def _near_misses_from_record(record: object) -> tuple[tuple[str, float], ...]:
    """Reconstruct the near-miss ``(phrase, score)`` pairs, dropping malformed rows."""
    if not isinstance(record, list):
        return ()
    pairs: list[tuple[str, float]] = []
    for item in record:
        if (
            isinstance(item, list)
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], (int, float))
        ):
            pairs.append((item[0], float(item[1])))
    return tuple(pairs)
