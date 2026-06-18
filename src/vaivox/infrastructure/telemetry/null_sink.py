"""No-op telemetry sink (Phase 3 default).

Preserves legacy behaviour, which recorded no telemetry. The JSONL sink and
near-miss capture (ADR-0006) replace this in Phase 5; wiring the port now means that
change is a composition-root edit, not a use-case change.
"""

from __future__ import annotations

import logging

from vaivox.domain.telemetry.model import ReconciliationOutcome

_LOGGER = logging.getLogger(__name__)


class NullTelemetrySink:
    """Discard every reconciliation outcome (logging it only at debug level)."""

    def record(self, outcome: ReconciliationOutcome) -> None:
        """Discard ``outcome`` (debug-logged for local troubleshooting)."""
        _LOGGER.debug("Telemetry (no-op): '%s' -> %s", outcome.command_text, outcome.destination)
