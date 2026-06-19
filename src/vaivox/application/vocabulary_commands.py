"""Vocabulary mutation use cases.

These commands keep UI/API drivers away from storage details: callers express a
vocabulary change, while the use case updates the structured repository through the port.
"""

from __future__ import annotations

import re
from dataclasses import replace

from vaivox.application.ports import Clock, VocabularyRepository
from vaivox.domain.vocabulary.model import (
    GovernedEntry,
    UsageStats,
    VocabularyEntry,
    VocabularyKind,
    VocabularyOrigin,
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class AddWordMapping:
    """Add or extend an alias-to-replacement word mapping."""

    def __init__(self, repository: VocabularyRepository, clock: Clock) -> None:
        """Wire the repository and clock ports.

        Args:
            repository: The structured vocabulary repository.
            clock: The clock used for usage seeding on new entries.
        """
        self._repository = repository
        self._clock = clock

    def execute(self, aliases: str, replacement: str) -> VocabularyEntry | None:
        """Add aliases that resolve to ``replacement``.

        Args:
            aliases: One or more semicolon-separated aliases.
            replacement: The canonical replacement term.

        Returns:
            The added or updated source entry, or ``None`` when the input is blank.
        """
        alias_terms = _parse_aliases(aliases)
        term = replacement.strip()
        if not alias_terms or not term:
            return None

        now = self._clock.now()
        governed = self._repository.load(VocabularyKind.WORD_MAPPING)
        existing_index = _matching_entry_index(governed, term)
        if existing_index is None:
            entry = VocabularyEntry(
                id=_unique_id(_slug(term), {entry.id for entry in governed}),
                kind=VocabularyKind.WORD_MAPPING,
                term=term,
                aliases=tuple(alias_terms),
                origin=VocabularyOrigin.DEFAULT,
            )
            self._repository.add(entry, now)
            return entry

        current = governed[existing_index]
        merged_aliases = tuple(sorted({*current.entry.aliases, *alias_terms}, key=str.casefold))
        updated_entry = replace(current.entry, aliases=merged_aliases)
        updated = GovernedEntry(
            entry=updated_entry,
            usage=current.usage if current.usage is not None else UsageStats(last_used=now),
        )
        kept = [*governed]
        kept[existing_index] = updated
        self._repository.replace_entries(VocabularyKind.WORD_MAPPING, kept)
        return updated_entry


def _parse_aliases(aliases: str) -> list[str]:
    """Parse semicolon-separated aliases, preserving first-seen order."""
    seen: set[str] = set()
    parsed: list[str] = []
    for raw_alias in aliases.split(";"):
        alias = raw_alias.strip()
        key = alias.casefold()
        if not alias or key in seen:
            continue
        seen.add(key)
        parsed.append(alias)
    return parsed


def _matching_entry_index(entries: list[GovernedEntry], term: str) -> int | None:
    """Return the index of the mapping entry for ``term``, if present."""
    normalized = term.casefold()
    for index, governed in enumerate(entries):
        if governed.entry.term.casefold() == normalized:
            return index
    return None


def _slug(text: str) -> str:
    """Slugify ``text`` into a stable id fragment."""
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return slug or "entry"


def _unique_id(base: str, seen: set[str]) -> str:
    """Return ``base`` or a suffixed id not already present in ``seen``."""
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate
