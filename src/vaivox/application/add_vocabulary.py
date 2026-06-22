"""Use case: add a word mapping through the vocabulary repository (ADR-0004).

The UI "Add word mapping" action used to append a line to the legacy flat
``word_mappings.txt`` — which the reconciliation engine no longer reads. This use case
routes the same action into the :class:`~vaivox.application.ports.VocabularyRepository`,
the single source of truth, so a user-added mapping is immediately visible both to the
engine (via the :class:`~vaivox.application.ports.VocabularyProvider` projection) and to the
introspection ``GET /vocabulary``.

Mappings are grouped by replacement (mirroring the migration): adding aliases for a
replacement that already has an entry **merges** the new aliases into that entry rather than
creating a duplicate, keeping the store shape identical to a fresh seed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace

from vaivox.application.ports import Clock, VocabularyRepository
from vaivox.domain.vocabulary.model import (
    VocabularyEntry,
    VocabularyKind,
    VocabularyOrigin,
)

_LOGGER = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class AddWordMapping:
    """Add (or extend) a word-mapping entry in the repository source of truth."""

    def __init__(self, repository: VocabularyRepository, clock: Clock) -> None:
        """Wire the vocabulary repository and the clock.

        Args:
            repository: The vocabulary repository (the JSONL source of truth).
            clock: The clock used to stamp a new entry's seed ``last_used`` (grace window).
        """
        self._repository = repository
        self._clock = clock

    def execute(self, aliases: str, replacement: str) -> None:
        """Add the ``;``-separated ``aliases`` as a mapping to ``replacement``.

        A blank ``aliases`` or ``replacement`` is ignored. If a ``WORD_MAPPING`` entry for
        ``replacement`` already exists, the new aliases are merged into it (de-duplicated,
        sorted); otherwise a fresh ``DEFAULT`` entry is added.

        Args:
            aliases: One or more ``;``-separated alias surface forms.
            replacement: The replacement text the aliases resolve to.
        """
        term = replacement.strip()
        new_aliases = [alias.strip() for alias in aliases.split(";") if alias.strip()]
        if not term or not new_aliases:
            return

        when = self._clock.now()
        existing = self._repository.load(VocabularyKind.WORD_MAPPING)
        match = next((governed for governed in existing if governed.entry.term == term), None)

        if match is None:
            entry = VocabularyEntry(
                id=_unique_id(_slug(term), {governed.id for governed in existing}),
                kind=VocabularyKind.WORD_MAPPING,
                term=term,
                aliases=tuple(sorted(set(new_aliases))),
                origin=VocabularyOrigin.DEFAULT,
            )
            self._repository.add(entry, when)
            _LOGGER.info("Added word mapping '%s' -> %s.", ";".join(new_aliases), term)
            return

        merged_aliases = tuple(sorted(set(match.entry.aliases) | set(new_aliases)))
        if merged_aliases == match.entry.aliases:
            return
        updated = replace(match, entry=replace(match.entry, aliases=merged_aliases))
        kept = [updated if governed.id == match.id else governed for governed in existing]
        self._repository.replace_entries(VocabularyKind.WORD_MAPPING, kept)
        _LOGGER.info("Extended word mapping for '%s' with %s.", term, new_aliases)


def _slug(text: str) -> str:
    """Slugify ``text`` into a stable id fragment (matches the migration's slugger)."""
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return slug or "entry"


def _unique_id(base: str, seen: set[str]) -> str:
    """Return ``base`` (or a ``base-N`` suffix) not already in ``seen``."""
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate
