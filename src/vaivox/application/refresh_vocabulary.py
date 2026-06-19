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
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from vaivox.application.ports import (
    MissionVocabularySnapshot,
    MissionVocabularySource,
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


@dataclass(frozen=True)
class MissionVocabularyRefreshResult:
    """Outcome of one mission-scoped vocabulary refresh pass.

    Attributes:
        changed: Whether the mission overlay changed and was applied.
        mission_phrases: Number of mission-only phrases in the latest snapshot.
        new_phrases: How many of those phrases were not present in the previous snapshot
            (the count surfaced to the operator when the F10 poll pulls fresh commands).
        live_phrases: Total live phrase-index size after applying the overlay, or
            ``None`` when nothing changed.
        source: Human-readable source location used by the adapter, if any.
        reason: Short status from the adapter.
    """

    changed: bool
    mission_phrases: int
    new_phrases: int = 0
    live_phrases: int | None = None
    source: str | None = None
    reason: str = "loaded"


class RefreshMissionVocabulary:
    """Refresh the ephemeral mission F10 overlay and hot-apply it when it changes."""

    def __init__(
        self,
        source: MissionVocabularySource,
        reporter: StatusReporter,
        apply_mission_snapshot: Callable[[MissionVocabularySnapshot], int],
        verbose: Callable[[], bool] | None = None,
    ) -> None:
        """Wire the source, reporter, live overlay apply hook, and verbose-logging gate.

        Args:
            source: Adapter that reads the current mission-only command phrases.
            reporter: User-facing status reporter.
            apply_mission_snapshot: Replaces the mission overlay in the live phrase and
                command-surface indexes, and returns the total phrase count now active.
            verbose: Optional predicate read each poll; when it returns ``True`` the use
                case emits a detailed F10 pull block (source, markers, match counts, the
                commands) to the reporter for debugging. ``None`` disables verbose logging.
        """
        self._source = source
        self._reporter = reporter
        self._apply_mission_snapshot = apply_mission_snapshot
        self._verbose = verbose
        self._phrases: tuple[str, ...] = ()
        self._verbose_logged = False

    def execute(self) -> MissionVocabularyRefreshResult:
        """Refresh the mission overlay if the discovered F10 phrases changed."""
        snapshot = self._source.load()
        changed = snapshot.phrases != self._phrases
        self._log_verbose_if_enabled(snapshot, changed)
        if not changed:
            return MissionVocabularyRefreshResult(
                changed=False,
                mission_phrases=len(snapshot.phrases),
                source=snapshot.source,
                reason=snapshot.reason,
            )

        previous_count = len(self._phrases)
        previous_keys = {phrase.lower() for phrase in self._phrases}
        new_count = sum(1 for phrase in snapshot.phrases if phrase.lower() not in previous_keys)
        self._phrases = snapshot.phrases
        live_phrases = self._apply_mission_snapshot(snapshot)
        mission_count = len(snapshot.phrases)

        if mission_count:
            new_suffix = f", {new_count} new" if new_count else ""
            self._reporter.report(
                f"Mission F10 vocabulary refreshed: {mission_count} commands pulled"
                f"{new_suffix} ({live_phrases} total)",
                StatusLevel.SUCCESS,
            )
        elif previous_count:
            self._reporter.report("Mission F10 vocabulary cleared", StatusLevel.INFO)

        return MissionVocabularyRefreshResult(
            changed=True,
            mission_phrases=mission_count,
            new_phrases=new_count,
            live_phrases=live_phrases,
            source=snapshot.source,
            reason=snapshot.reason,
        )

    def _log_verbose_if_enabled(self, snapshot: MissionVocabularySnapshot, changed: bool) -> None:
        """Emit the verbose F10 pull log when enabled (full block on change/first, else one line).

        The full block is logged the first time verbose logging is seen (so toggling it on
        always yields detail) and on every change; otherwise an unchanged poll logs a single
        line so the operator can confirm the poll runs without flooding the log every cycle.
        """
        if self._verbose is None or not self._verbose():
            self._verbose_logged = False
            return
        if changed or not self._verbose_logged:
            self._verbose_logged = True
            self._report_verbose_detail(snapshot)
        else:
            self._reporter.report(
                f"Mission F10 poll: unchanged ({len(snapshot.phrases)} commands "
                f"from {snapshot.source or 'no log'})",
                StatusLevel.DETAIL,
            )

    def _report_verbose_detail(self, snapshot: MissionVocabularySnapshot) -> None:
        """Report the detailed F10 pull block: resolved source, match counts, and commands."""
        self._reporter.report("Mission F10 pull:", StatusLevel.DETAIL)
        diagnostics = snapshot.diagnostics
        if diagnostics is not None:
            latest = (
                f", latest mission: {diagnostics.latest_mission}"
                if (diagnostics.latest_mission)
                else ""
            )
            self._reporter.report(
                f"  log: {diagnostics.log_path or 'not found'} ({diagnostics.file_bytes} bytes)",
                StatusLevel.DETAIL,
            )
            self._reporter.report(
                f"  mission markers: {diagnostics.mission_markers}{latest}", StatusLevel.DETAIL
            )
            self._reporter.report(
                f"  F10 matches: current-mission={diagnostics.scoped_matches}, "
                f"whole-log={diagnostics.whole_log_matches}, "
                f"fallback={'yes' if diagnostics.fallback_used else 'no'}",
                StatusLevel.DETAIL,
            )
        self._reporter.report(
            f"  result: {len(snapshot.phrases)} commands ({snapshot.reason})", StatusLevel.DETAIL
        )
        self._report_phrase_listing(snapshot.phrases)

    def _report_phrase_listing(self, phrases: Sequence[str]) -> None:
        """List the pulled commands (capped) so an empty/partial pull is fully visible."""
        listing_cap = 50
        for index, phrase in enumerate(phrases[:listing_cap], start=1):
            self._reporter.report(f"    {index}. {phrase}", StatusLevel.DETAIL)
        if len(phrases) > listing_cap:
            self._reporter.report(
                f"    ... and {len(phrases) - listing_cap} more", StatusLevel.DETAIL
            )
