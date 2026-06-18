"""Use case: request an orderly application shutdown."""

from __future__ import annotations

import logging
from collections.abc import Callable

from vaivox.application.ports import StatusReporter

_LOGGER = logging.getLogger(__name__)


class Shutdown:
    """Signal the application to stop in response to a shutdown command."""

    def __init__(self, request_shutdown: Callable[[], None], reporter: StatusReporter) -> None:
        """Wire the shutdown callback and status reporter.

        Args:
            request_shutdown: Callback that stops the control loop and closes the app.
            reporter: The user-facing status reporter port.
        """
        self._request_shutdown = request_shutdown
        self._reporter = reporter

    def execute(self) -> None:
        """Report the shutdown and invoke the shutdown callback."""
        _LOGGER.info("Received shutdown command. Stopping server...")
        self._reporter.report("Received shutdown command. Stopping server...")
        self._request_shutdown()
