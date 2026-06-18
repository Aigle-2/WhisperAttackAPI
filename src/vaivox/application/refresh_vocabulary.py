"""Use case: regenerate the VAICOM vocabulary when stale and hot-apply it (ADR-0005/0009).

VAICOM-derived vocabulary is never shipped (ADR-0005): it is generated locally from the
user's own install, transparently, on first run and whenever it goes stale. This use case
is the *trigger logic* — it decides whether generation is warranted, drives the
:class:`~vaivox.application.ports.VocabularyGenerator` port, reports progress through the
:class:`~vaivox.application.ports.StatusReporter`, and on success asks the composition root
to hot-apply the regenerated phrase index (ADR-0009, via the reloadable snapper). It owns
no I/O or threading itself, so it runs the same whether called on a background startup
thread or from a UI "Refresh VAICOM vocabulary" action (``force=True``).

The keyterm file is read by the STT backend at load time, so a regenerated keyterm list
takes effect on the next launch; only the phrase index is hot-applied in the live session.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from vaivox.application.ports import (
    StatusLevel,
    StatusReporter,
    VocabularyGenerationResult,
    VocabularyGenerator,
)

_LOGGER = logging.getLogger(__name__)


class RefreshVocabulary:
    """Generate the VAICOM vocabulary when stale and hot-apply the new phrase index."""

    def __init__(
        self,
        generator: VocabularyGenerator,
        reporter: StatusReporter,
        apply_phrase_index: Callable[[], int],
    ) -> None:
        """Wire the generator port, the status reporter, and the hot-apply hook.

        Args:
            generator: The vocabulary generator port (the VAICOM adapter in production).
            reporter: The user-facing status reporter port.
            apply_phrase_index: Called after a successful generation to swap the
                regenerated phrase index into the live snapper (ADR-0009), returning the
                number of phrases now live. Injected by the composition root so this use
                case stays free of infrastructure.
        """
        self._generator = generator
        self._reporter = reporter
        self._apply_phrase_index = apply_phrase_index

    def execute(self, force: bool = False) -> VocabularyGenerationResult:
        """Refresh the vocabulary if it is stale (or ``force``), reporting the outcome.

        Args:
            force: Regenerate even if the vocabulary looks up to date (the UI "Refresh"
                action); startup passes ``False`` so an up-to-date install is left alone.

        Returns:
            The :class:`~vaivox.application.ports.VocabularyGenerationResult` — quietly
            reporting ``generated=False`` when up to date or no install was found.
        """
        if not force and not self._generator.is_stale():
            _LOGGER.debug("VAICOM vocabulary is up to date; skipping generation.")
            return VocabularyGenerationResult(generated=False, reason="up to date")

        self._reporter.report("Refreshing VAICOM vocabulary...", StatusLevel.DETAIL)
        result = self._generator.generate()

        if result.generated:
            _LOGGER.info(
                "Generated VAICOM vocabulary from %s: %d phrases, %d keyterms.",
                result.source,
                result.phrase_count,
                result.keyterm_count,
            )
            self._reporter.report(
                f"VAICOM vocabulary generated: {result.phrase_count} phrases, "
                f"{result.keyterm_count} keyterms",
                StatusLevel.SUCCESS,
            )
            self._apply_phrase_index()
        else:
            _LOGGER.info("VAICOM vocabulary not generated: %s.", result.reason)
            self._reporter.report(
                f"VAICOM vocabulary not generated: {result.reason} — using the built-in seed",
                StatusLevel.INFO,
            )
        return result


@dataclass(frozen=True)
class ReloadResult:
    """The outcome of a vocabulary reload-from-disk (ADR-0009 / ADR-0010 reload action).

    Attributes:
        reloaded: Always ``True`` when the reload was requested (it re-reads the current
            on-disk phrase index and swaps it in at idle).
        phrases: The number of phrases now live after the reload.
    """

    reloaded: bool
    phrases: int


class ReloadVocabulary:
    """Re-read the on-disk phrase index and hot-apply it (ADR-0009 reload, no generation).

    The counterpart to :class:`RefreshVocabulary` that does **not** regenerate from VAICOM:
    it just re-reads the current files and swaps them in (e.g. after a hand-edit), via the
    same idle-gated reload hook the composition root injects. A gated debug/agent action.
    """

    def __init__(self, apply_phrase_index: Callable[[], int], reporter: StatusReporter) -> None:
        """Wire the hot-apply hook and the status reporter.

        Args:
            apply_phrase_index: Re-reads the on-disk phrase index and swaps it into the
                live snapper (ADR-0009), returning the number of phrases now live.
            reporter: The user-facing status reporter port.
        """
        self._apply_phrase_index = apply_phrase_index
        self._reporter = reporter

    def execute(self) -> ReloadResult:
        """Reload the phrase index from disk and return how many phrases are now live."""
        self._reporter.report("Reloading vocabulary from disk...", StatusLevel.DETAIL)
        phrases = self._apply_phrase_index()
        return ReloadResult(reloaded=True, phrases=phrases)
