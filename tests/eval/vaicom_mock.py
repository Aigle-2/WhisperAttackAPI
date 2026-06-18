"""VAICOM mock + match oracle for the offline reconciliation eval (ADR-0008).

A test double over a known command set that answers ``exists`` exactly like the real
plugin's ``vaProxy.Command.Exists`` (case/whitespace-insensitive), plus a ``nearest``
helper (rapidfuzz) used for near-miss quality. The same object can back a ``CommandSink``
double for attribution tests later. No VoiceAttack, DCS, or network involved.
"""

from __future__ import annotations

from collections.abc import Iterable

from rapidfuzz import fuzz, process


def normalize(text: str) -> str:
    """Normalize a command phrase for matching (lowercase, collapse whitespace)."""
    return " ".join(text.lower().split())


class VaicomMock:
    """Match oracle over a frozen command set."""

    def __init__(self, commands: Iterable[str]) -> None:
        self._index: dict[str, str] = {}
        for command in commands:
            key = normalize(command)
            if key:
                self._index[key] = command

    def exists(self, command: str) -> bool:
        """Return whether ``command`` matches a known command (Command.Exists semantics)."""
        return normalize(command) in self._index

    def nearest(self, command: str, limit: int = 3) -> list[str]:
        """Return the ``limit`` nearest known commands to ``command`` (rapidfuzz)."""
        matches = process.extract(
            normalize(command),
            list(self._index.keys()),
            scorer=fuzz.token_sort_ratio,
            limit=limit,
        )
        return [self._index[key] for key, _score, _position in matches]
