"""Structured vocabulary projection for the reconciliation pipeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vaivox.application.ports import VocabularyRepository
from vaivox.domain.vocabulary.model import VocabularyKind


class RepositoryReconciliationVocabulary:
    """Project structured vocabulary entries into reconciliation inputs.

    The domain reconciliation pipeline still accepts the legacy-shaped data it needs:
    ``alias -> replacement`` mappings and a fuzzy-word list. This adapter builds those
    shapes from the structured repository at read time, keeping storage out of config.
    """

    def __init__(self, repository: VocabularyRepository) -> None:
        """Bind the projection to ``repository``."""
        self._repository = repository

    def get_word_mappings(self) -> Mapping[str, str]:
        """Return aliases from structured ``WORD_MAPPING`` entries."""
        mappings: dict[str, str] = {}
        for governed in self._repository.load(VocabularyKind.WORD_MAPPING):
            for alias in governed.entry.aliases:
                mappings[alias] = governed.entry.term
        return mappings

    def get_fuzzy_words(self) -> Sequence[str]:
        """Return terms from structured ``FUZZY_WORD`` entries."""
        return [
            governed.entry.term
            for governed in self._repository.load(VocabularyKind.FUZZY_WORD)
            if governed.entry.term.strip()
        ]


__all__ = ["RepositoryReconciliationVocabulary"]
