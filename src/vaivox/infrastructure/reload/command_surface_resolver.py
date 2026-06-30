"""Thread-safe hot-reload wrapper for command-surface resolution."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from threading import Lock
from typing import Protocol

from vaivox.domain.commands.model import CommandResolution, CommandSurface


class _ResolverSnapshot(Protocol):
    """Frozen command-surface resolver snapshot."""

    @property
    def surfaces(self) -> tuple[CommandSurface, ...]:
        """The command surfaces this snapshot resolves against."""

    def resolve(self, text: str) -> CommandResolution:
        """Resolve ``text`` to a command surface, or abstain/raw."""


class ReloadableCommandSurfaceResolver:
    """A command-surface matcher whose frozen resolver can be swapped atomically."""

    def __init__(
        self,
        surfaces: Sequence[CommandSurface],
        build: Callable[[Sequence[CommandSurface]], _ResolverSnapshot],
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
