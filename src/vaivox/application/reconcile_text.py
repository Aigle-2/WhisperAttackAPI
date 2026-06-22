"""The single application entry point into the reconciliation pipeline.

Every flow that turns text into a command — the push-to-talk path
(:class:`~vaivox.application.record_command.StopAndReconcile`), the gated simulate
action (:class:`~vaivox.application.record_command.SimulateUtterance`), and the read-only
dry-run query (:class:`~vaivox.application.queries.DryRunReconcile`) — delegates here, so
the call into the domain :func:`~vaivox.domain.reconciliation.pipeline.reconcile` (its
vocabulary read, the :data:`~vaivox.domain.vocabulary.keyterms.PHONETIC_ALPHABET`, and the
fuzzy threshold) lives in exactly one place.

The fuzzy threshold is **not** redeclared here: :func:`reconcile` already defaults it to the
domain's :data:`~vaivox.domain.reconciliation.pipeline._DEFAULT_FUZZY_THRESHOLD`, the single
source of truth. Omitting the argument inherits that default, so there is no duplicated
magic value on the application side.
"""

from __future__ import annotations

from vaivox.application.ports import VocabularyProvider
from vaivox.domain.reconciliation.model import ReconciliationResult
from vaivox.domain.reconciliation.pipeline import reconcile
from vaivox.domain.vocabulary.keyterms import PHONETIC_ALPHABET


class ReconcileText:
    """Reconcile raw text into a command, reading vocabulary live (ADR-0004).

    A thin collaborator the use cases compose over rather than calling the domain
    :func:`reconcile` directly. It owns the :class:`VocabularyProvider` and the
    pipeline's invariant arguments (the phonetic alphabet and the fuzzy threshold), so the
    three reconciliation flows stay in lock-step on the same seams.
    """

    def __init__(self, vocabulary: VocabularyProvider) -> None:
        """Wire the vocabulary provider read on every reconciliation.

        Args:
            vocabulary: The vocabulary provider port (the repository-backed projection in
                production, ADR-0004), read **live** so a mapping added while the app runs
                is visible on the next call.
        """
        self._vocabulary = vocabulary

    def execute(self, text: str) -> ReconciliationResult:
        """Reconcile ``text`` into a command, staging each transformation.

        Reads the word mappings and fuzzy words from the provider, then runs the domain
        pipeline with the NATO phonetic alphabet and the domain-default fuzzy threshold.

        Args:
            text: The raw transcript to reconcile.

        Returns:
            The staged raw -> cleaned -> command :class:`ReconciliationResult`.
        """
        return reconcile(
            text,
            self._vocabulary.get_word_mappings(),
            self._vocabulary.get_fuzzy_words(),
            PHONETIC_ALPHABET,
        )
