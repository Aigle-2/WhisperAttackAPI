"""System clock adapter for the :class:`~vaivox.application.ports.Clock` port."""

from __future__ import annotations

from datetime import datetime


class SystemClock:
    """Read the wall-clock time from the operating system."""

    def now(self) -> datetime:
        """Return the current local time."""
        return datetime.now()
