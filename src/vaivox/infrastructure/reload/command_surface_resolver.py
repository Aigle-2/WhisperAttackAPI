"""Thread-safe hot-reload wrapper for command-surface resolution."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from threading import Lock

from vaivox.domain.commands.model import CommandResolution, CommandSurface
from vaivox.domain.commands.resolver import CommandSurfaceResolver


class ReloadableCommandSurfaceResolver:
    """A command-surface matcher whose frozen resolver can be swapped atomically."""

    def __init__(
        self,
        surfaces: Sequence[CommandSurface],
        build: Callable[[Sequence[CommandSurface]], CommandSurfaceResolver],
    ) -> None:
        """Build the initial resolver and remember the builder for reloads."""
        self._build = build
        self._lock = Lock()
        self._resolver = build(tuple(surfaces))

    @property
    def surfaces(self) -> tuple[CommandSurface, ...]:
        """The currently active command surfaces."""
        with self._lock:
            return self._resolver.surfaces

    def resolve(self, text: str) -> CommandResolution:
        """Resolve ``text`` using the current resolver snapshot."""
        with self._lock:
            resolver = self._resolver
        return resolver.resolve(text)

    def reload(self, surfaces: Sequence[CommandSurface]) -> int:
        """Atomically replace the active surface index and return its size."""
        resolver = self._build(tuple(surfaces))
        with self._lock:
            self._resolver = resolver
        return len(resolver.surfaces)
