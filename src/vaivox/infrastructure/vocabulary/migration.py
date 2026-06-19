"""One-shot migration of the legacy flat vocabulary into the JSONL source (ADR-0004).

The legacy app stored vocabulary as flat text: ``fuzzy_words.txt`` (one word per line) and
``word_mappings.txt`` (``alias1;alias2=replacement`` lines). ADR-0004 moves both to the
structured JSONL source the :class:`~vaivox.application.ports.VocabularyRepository` reads —
stable ``id``, ``aliases``, ``origin``. This module converts the in-memory legacy shapes
parsed by :mod:`vaivox.infrastructure.vocabulary.legacy_files` into
:class:`~vaivox.domain.vocabulary.model.VocabularyEntry` records and seeds them through the
repository.

It is a one-shot compatibility utility (run via ``tools/migrate_vocabulary.py`` or startup
upgrade code); the live pipeline reads structured vocabulary through the repository-backed
projection port.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from vaivox.application.ports import VocabularyRepository
from vaivox.domain.vocabulary.model import VocabularyEntry, VocabularyKind, VocabularyOrigin

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class MigrationReport:
    """How many entries the migration produced, by kind (ADR-0004).

    Attributes:
        fuzzy_words: The number of fuzzy-word entries migrated.
        word_mappings: The number of word-mapping entries migrated (grouped by replacement).
    """

    fuzzy_words: int
    word_mappings: int

    @property
    def total(self) -> int:
        """The total number of entries migrated across kinds."""
        return self.fuzzy_words + self.word_mappings


def legacy_to_entries(
    word_mappings: Mapping[str, str], fuzzy_words: Sequence[str]
) -> list[VocabularyEntry]:
    """Convert the legacy flat vocabulary into structured entries (pure, deterministic).

    Fuzzy words become one ``FUZZY_WORD`` entry each. Word mappings are grouped by
    replacement, so every alias of one replacement collapses into a single ``WORD_MAPPING``
    entry with the replacement as ``term`` and the aliases sorted. Ids are slugs of the term,
    de-duplicated within each kind; every entry is ``DEFAULT`` origin (curated, protected).

    Args:
        word_mappings: The legacy ``alias -> replacement`` mapping.
        fuzzy_words: The legacy fuzzy-correction words.

    Returns:
        The structured entries — fuzzy words first, then word mappings — in input order.
    """
    entries: list[VocabularyEntry] = []

    fuzzy_ids: set[str] = set()
    for word in fuzzy_words:
        term = word.strip()
        if not term:
            continue
        entries.append(
            VocabularyEntry(
                id=_unique_id(_slug(term), fuzzy_ids),
                kind=VocabularyKind.FUZZY_WORD,
                term=term,
                origin=VocabularyOrigin.DEFAULT,
            )
        )

    grouped: dict[str, list[str]] = {}
    for raw_alias, raw_replacement in word_mappings.items():
        term = raw_replacement.strip()
        alias = raw_alias.strip()
        if not term or not alias:
            continue
        grouped.setdefault(term, []).append(alias)

    mapping_ids: set[str] = set()
    for term, aliases in grouped.items():
        entries.append(
            VocabularyEntry(
                id=_unique_id(_slug(term), mapping_ids),
                kind=VocabularyKind.WORD_MAPPING,
                term=term,
                aliases=tuple(sorted(set(aliases))),
                origin=VocabularyOrigin.DEFAULT,
            )
        )

    return entries


def migrate_legacy_vocabulary(
    word_mappings: Mapping[str, str],
    fuzzy_words: Sequence[str],
    repository: VocabularyRepository,
    when: datetime,
) -> MigrationReport:
    """Seed the structured JSONL source from the legacy vocabulary (idempotent by id).

    Each converted entry is added through the repository, which skips ids already present —
    so re-running the migration never duplicates entries.

    Args:
        word_mappings: The legacy ``alias -> replacement`` mapping.
        fuzzy_words: The legacy fuzzy-correction words.
        repository: The vocabulary repository to seed.
        when: The creation time stamped as the entries' seed ``last_used``.

    Returns:
        A :class:`MigrationReport` of how many entries were produced per kind.
    """
    entries = legacy_to_entries(word_mappings, fuzzy_words)
    for entry in entries:
        repository.add(entry, when)
    fuzzy = sum(1 for entry in entries if entry.kind is VocabularyKind.FUZZY_WORD)
    mappings = sum(1 for entry in entries if entry.kind is VocabularyKind.WORD_MAPPING)
    return MigrationReport(fuzzy_words=fuzzy, word_mappings=mappings)


def _slug(text: str) -> str:
    """Slugify ``text`` into a stable id fragment (lowercase, non-alphanumeric -> ``-``)."""
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return slug or "entry"


def _unique_id(base: str, seen: set[str]) -> str:
    """Return ``base`` (or a ``base-N`` suffix) not already in ``seen``, recording the choice."""
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}-{counter}"
        counter += 1
    seen.add(candidate)
    return candidate
