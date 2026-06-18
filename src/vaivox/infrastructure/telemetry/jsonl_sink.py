"""Append-only JSONL telemetry sink (ADR-0006 step 1, "Telemetry (always)").

The :class:`~vaivox.application.ports.TelemetrySink` adapter. Each
:class:`~vaivox.domain.telemetry.model.ReconciliationOutcome` is serialized with
:func:`dataclasses.asdict` (which recurses into the nested
:class:`~vaivox.domain.telemetry.model.MatchOutcome`) and appended as one JSON line to
``telemetry.jsonl`` in the per-user VAIVOX data directory under %LOCALAPPDATA%.

Persistence is best-effort and degrades gracefully (ADR-0006 "Boundaries &
robustness"): any I/O or serialization failure is logged and swallowed so telemetry
can never raise into the ``StopAndReconcile`` use case or block the user. Until the
plugin return channel is wired (a later Phase 5 increment), the ``match`` field is
recorded as ``null`` (unknown) exactly as the use case emits it today.

Stdlib only (``json``, ``pathlib``) — no runtime dependency and nothing heavy at
import time, so the package smoke test keeps importing this module cleanly.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from vaivox.domain.telemetry.model import ReconciliationOutcome

_LOGGER = logging.getLogger(__name__)

TELEMETRY_FILE = "telemetry.jsonl"


class JsonlTelemetrySink:
    """Persist each reconciliation outcome as one JSON line in the data directory.

    Writes are plain appends in newline-delimited JSON: one self-contained record per
    utterance, so the log stays append-only and trivially streamable for the offline
    review report (ADR-0006 action item 4).

    Args:
        data_dir: The per-user VAIVOX data directory the telemetry log lives in.
    """

    def __init__(self, data_dir: str) -> None:
        """Bind the sink to ``data_dir`` (the path is resolved lazily per record)."""
        self._path = Path(data_dir) / TELEMETRY_FILE

    def record(self, outcome: ReconciliationOutcome) -> None:
        """Append ``outcome`` to the telemetry log, swallowing any write failure.

        Args:
            outcome: The full provenance of one utterance to persist.
        """
        try:
            line = json.dumps(asdict(outcome), ensure_ascii=False)
        except (TypeError, ValueError) as error:
            # Defensive: a non-serializable outcome must never crash the use case.
            _LOGGER.warning("Failed to serialize telemetry outcome: %s", error)
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as file:
                file.write(f"{line}\n")
        except OSError as error:
            _LOGGER.warning("Failed to append telemetry to '%s': %s", self._path, error)
