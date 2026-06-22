"""Project the structured vocabulary repository into the flat reconciliation reads (ADR-0004).

The reconciliation pipeline consumes two flat shapes — ``word_mappings`` (alias-to-
replacement) and ``fuzzy_words`` (a word list). ADR-0004 makes the
:class:`~vaivox.application.ports.VocabularyRepository` (the JSONL source + usage sidecar)
the single source of truth those reads come from, so the engine and the introspection
``GET /vocabulary`` never diverge. This adapter is the projection: it satisfies the
:class:`~vaivox.application.ports.VocabularyProvider` port by reading the repository and
flattening its :class:`~vaivox.domain.vocabulary.model.GovernedEntry` records back into the
shapes the pipeline expects.

The flattening is the inverse of the one-shot migration
(:mod:`vaivox.infrastructure.vocabulary.migration`): a ``WORD_MAPPING`` entry holds the
replacement as ``term`` and the aliases that resolve to it, so each ``alias -> term`` pair is
re-emitted; a ``FUZZY_WORD`` entry contributes its ``term``. Reading the repository each call
keeps the view **live** — a mapping added through the UI (``VocabularyRepository.add``) is
visible on the next utterance — while a tiny TTL cache avoids re-parsing the JSONL on every
read in a burst of utterances without ever serving stale data for longer than the window.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vaivox.application.ports import Clock, VocabularyRepository
from vaivox.domain.vocabulary.model import GovernedEntry, VocabularyKind

_LOGGER = logging.getLogger(__name__)

#: How long a flattened projection is reused before the repository is re-read. Short enough
#: that a UI-added mapping appears within a second; long enough that a burst of utterances
#: does not re-parse the JSONL each time.
_CACHE_TTL_SECONDS = 1.0


@dataclass
class _CachedView:
    """A flattened projection plus the monotonic time it was built, for the TTL cache."""

    word_mappings: dict[str, str]
    fuzzy_words: list[str]
    built_at: float


class RepositoryVocabularyProvider:
    """Read the reconciliation vocabulary from the repository (a :class:`VocabularyProvider`).

    Args:
        repository: The structured vocabulary repository (the JSONL source of truth).
        clock: The clock used to age the in-memory projection cache. The cache only avoids
            re-parsing within a sub-second window; correctness never depends on it.
    """

    def __init__(self, repository: VocabularyRepository, clock: Clock) -> None:
        """Bind the repository and clock; the projection is built lazily on first read."""
        self._repository = repository
        self._clock = clock
        self._cache: _CachedView | None = None

    def get_word_mappings(self) -> Mapping[str, str]:
        """Return the effective alias-to-replacement mappings, projected from the repository.

        Returns:
            One ``alias -> term`` entry per alias of every ``WORD_MAPPING`` record. A later
            alias wins on a collision (last-write-wins), matching the legacy flat-file load.
        """
        return self._view().word_mappings

    def get_fuzzy_words(self) -> Sequence[str]:
        """Return the fuzzy-correction candidate words, projected from the repository.

        Returns:
            The ``term`` of every ``FUZZY_WORD`` record, in repository order.
        """
        return self._view().fuzzy_words

    def _view(self) -> _CachedView:
        """Return the live flattened projection, rebuilding it when the TTL has elapsed."""
        now = self._clock.now().timestamp()
        cache = self._cache
        if cache is not None and now - cache.built_at < _CACHE_TTL_SECONDS:
            return cache
        view = _CachedView(
            word_mappings=self._project_word_mappings(),
            fuzzy_words=self._project_fuzzy_words(),
            built_at=now,
        )
        self._cache = view
        return view

    def _project_word_mappings(self) -> dict[str, str]:
        """Flatten every ``WORD_MAPPING`` entry back into ``alias -> term`` pairs."""
        mappings: dict[str, str] = {}
        for governed in self._load(VocabularyKind.WORD_MAPPING):
            term = governed.entry.term
            for alias in governed.entry.aliases:
                mappings[alias] = term
        return mappings

    def _project_fuzzy_words(self) -> list[str]:
        """Collect the ``term`` of every ``FUZZY_WORD`` entry, in repository order."""
        return [governed.entry.term for governed in self._load(VocabularyKind.FUZZY_WORD)]

    def _load(self, kind: VocabularyKind) -> list[GovernedEntry]:
        """Load one kind from the repository, degrading to empty on any read failure."""
        try:
            return self._repository.load(kind)
        except Exception as error:  # pragma: no cover - the repository already logs + degrades
            _LOGGER.warning("Failed to load vocabulary kind %s: %s", kind.value, error)
            return []
