"""Structured vocabulary value objects (ADR-0004, Axis A).

Vocabularies (fuzzy words, word mappings, future aliases) move from flat text to
**structured entries** with a stable ``id`` and an ``origin``. Source content
(curated, versioned) is split from usage telemetry (machine-written, hot, local) so
the two natures never fight: this module models that split as two immutable value
objects joined on ``id``.

- :class:`VocabularyEntry` — the source record (curated or learned).
- :class:`UsageStats` — the mutable usage sidecar record (``last_used`` / ``hits``).
- :class:`GovernedEntry` — the read-time join the governor ranks and evicts on.

Pure value objects only (ADR-0001): no I/O. Reading and writing the JSONL source and
the usage sidecar is an infrastructure concern (see
:mod:`vaivox.infrastructure.vocabulary`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum


class VocabularyOrigin(Enum):
    """Where a vocabulary entry came from, which governs whether it can be evicted.

    Attributes:
        DEFAULT: Curated, human/UI-authored content shipped or hand-edited in the
            JSONL source. Protected from LRU eviction (ADR-0004 §3).
        LEARNED: Content proposed by the feedback loop (ADR-0006) and accepted. Only
            ``LEARNED`` entries are candidates for eviction.
    """

    DEFAULT = "default"
    LEARNED = "learned"


class VocabularyKind(Enum):
    """The vocabulary a record belongs to (each file is capped independently).

    Attributes:
        FUZZY_WORD: A candidate word for fuzzy correction (legacy ``fuzzy_words.txt``).
        WORD_MAPPING: An alias-to-replacement mapping (legacy ``word_mappings.txt``).
        ALIAS: A future call-sign / phrase alias (reserved; not yet populated).
    """

    FUZZY_WORD = "fuzzy_word"
    WORD_MAPPING = "word_mapping"
    ALIAS = "alias"


@dataclass(frozen=True)
class VocabularyEntry:
    """A single structured vocabulary record — the versioned, editable *source*.

    The ``id`` is the stable join key to the usage sidecar; usage telemetry
    (``last_used`` / ``hits``) is deliberately *not* stored here so curated content
    stays diff-friendly and hot usage writes never touch it (ADR-0004 Option A).

    Attributes:
        id: Stable identifier, unique within a :class:`VocabularyKind`. The join key
            to :class:`UsageStats`.
        kind: Which vocabulary this record belongs to.
        term: The canonical term — the fuzzy word, or a mapping's replacement.
        aliases: Alternate surface forms that resolve to ``term`` (e.g. the left-hand
            side of a word mapping). Empty for a plain fuzzy word.
        origin: ``DEFAULT`` (protected) or ``LEARNED`` (evictable).
    """

    id: str
    kind: VocabularyKind
    term: str
    aliases: tuple[str, ...] = ()
    origin: VocabularyOrigin = VocabularyOrigin.DEFAULT

    @property
    def is_evictable(self) -> bool:
        """Whether LRU governance may evict this entry (only ``LEARNED`` entries)."""
        return self.origin is VocabularyOrigin.LEARNED


@dataclass(frozen=True)
class UsageStats:
    """Mutable usage telemetry for one entry — the *sidecar*, keyed by ``id``.

    Never committed to git (ADR-0004): it is written hot in the per-user VAIVOX data
    directory. A brand-new entry has ``hits == 0`` and ``last_used`` set to the
    creation time so the grace window can protect it from immediate eviction.

    Attributes:
        last_used: When the entry last contributed to a match (recency signal). For a
            never-used entry this is its creation/seed time.
        hits: How many matches the entry has contributed to (frequency signal).
    """

    last_used: datetime
    hits: int = 0

    def stamped(self, when: datetime) -> UsageStats:
        """Return a copy stamped as used at ``when`` (one more hit, refreshed recency).

        Args:
            when: The time the entry contributed to a match.

        Returns:
            A new :class:`UsageStats` with ``last_used = when`` and ``hits`` incremented.
        """
        return replace(self, last_used=when, hits=self.hits + 1)


@dataclass(frozen=True)
class GovernedEntry:
    """A source entry joined with its usage stats — what the governor ranks on.

    Attributes:
        entry: The source :class:`VocabularyEntry`.
        usage: Its joined :class:`UsageStats`.
    """

    entry: VocabularyEntry
    usage: UsageStats

    @property
    def id(self) -> str:
        """The underlying entry id (sidecar join key)."""
        return self.entry.id

    @property
    def is_evictable(self) -> bool:
        """Whether the underlying entry may be evicted (delegates to the entry)."""
        return self.entry.is_evictable


@dataclass(frozen=True)
class EvictionPolicy:
    """Per-vocabulary governance limits (reuses the ``KeytermBudget`` shape, ADR-0004).

    Attributes:
        max_entries: Cap on entries of one kind; ``None`` means unlimited (no
            eviction). Mirrors ``KeytermBudget.max_terms``.
        grace_window: A brand-new entry whose age (``now - last_used``) is below this
            is never evicted, so a just-added entry survives until it has had a chance
            to be used. ``None`` disables the grace window.
    """

    max_entries: int | None = None
    grace_window: timedelta | None = None

    def __post_init__(self) -> None:
        """Validate the policy fields after construction."""
        if self.max_entries is not None and self.max_entries < 0:
            raise ValueError("max_entries must be non-negative or None")


@dataclass(frozen=True)
class EvictionResult:
    """The outcome of one LRU maintenance pass over a single vocabulary.

    Attributes:
        kept: The retained entries, in the governor's ranking order (most useful
            first). Length is at most ``EvictionPolicy.max_entries``.
        evicted: The entries removed this pass (least-recently-used learned entries
            over the cap, outside the grace window).
    """

    kept: tuple[GovernedEntry, ...] = field(default_factory=tuple)
    evicted: tuple[GovernedEntry, ...] = field(default_factory=tuple)

    @property
    def evicted_ids(self) -> tuple[str, ...]:
        """The ids of the evicted entries (for the UI "evicted N" signal, ADR-0009)."""
        return tuple(governed.id for governed in self.evicted)


def credited_ids(governed_entries: Sequence[GovernedEntry]) -> tuple[str, ...]:
    """Return the ids of the supplied governed entries, de-duplicated, order-preserving.

    A small helper used by attribution to turn the contributing entries into the id
    list passed to ``VocabularyRepository.mark_used`` (ADR-0006 §2).

    Args:
        governed_entries: The entries credited with a match.

    Returns:
        Their unique ids in first-seen order.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for governed in governed_entries:
        if governed.id in seen:
            continue
        seen.add(governed.id)
        ordered.append(governed.id)
    return tuple(ordered)
