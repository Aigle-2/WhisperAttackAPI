"""Resolve reconciled text to typed command surfaces.

The resolver is deliberately pure: it knows about command surfaces and dispatch target
types, but it performs no I/O and does not dispatch anything. This keeps VAICOM/DCS and
VoiceAttack mechanics in adapters while letting the application route by typed intent.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

from vaivox.domain.commands.model import (
    CommandResolution,
    CommandResolutionDecision,
    CommandSurface,
    DispatchTargetKind,
    VaicomF10Action,
)
from vaivox.domain.reconciliation.snapper import DEFAULT_HIGH, DEFAULT_LOW, DEFAULT_MARGIN

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)


@dataclass(frozen=True)
class _SurfaceScore:
    surface: CommandSurface
    matched_alias: str
    score: float


class CommandSurfaceResolver:
    """Resolve text against a frozen command-surface index.

    Exact matches are resolved before fuzzy matches, with active mission F10 actions
    taking priority over static VoiceAttack commands. Fuzzy matches use the same
    conservative high/low/margin thresholds as phrase snap, and abstain when the best
    match is too close to the runner-up.
    """

    def __init__(
        self,
        surfaces: Iterable[CommandSurface],
        high: float = DEFAULT_HIGH,
        low: float = DEFAULT_LOW,
        margin: float = DEFAULT_MARGIN,
    ) -> None:
        """Freeze the surface index and resolution thresholds."""
        self._surfaces = tuple(surfaces)
        self._high = high
        self._low = low
        self._margin = margin

    @property
    def surfaces(self) -> tuple[CommandSurface, ...]:
        """The frozen command-surface index."""
        return self._surfaces

    def resolve(self, text: str) -> CommandResolution:
        """Resolve ``text`` to a command surface or abstain/raw.

        Args:
            text: The reconciled command text before typed dispatch.

        Returns:
            A command resolution. Only ``RESOLVED`` should trigger typed dispatch.
            ``ABSTAINED`` carries the best candidate for diagnostics; ``RAW`` means no
            useful surface was found and callers may use their legacy fallback.
        """
        query = _normalize(text)
        if not query or not self._surfaces:
            return CommandResolution(CommandResolutionDecision.RAW)

        exact = self._exact_matches(query)
        if exact:
            return self._resolve_exact(exact)

        scored = self._score_surfaces(query)
        if not scored:
            return CommandResolution(CommandResolutionDecision.RAW)

        for kind in (DispatchTargetKind.VAICOM_F10_ACTION, DispatchTargetKind.VOICEATTACK):
            best = _best_for_kind(scored, kind)
            if best is None or best.score < self._high:
                continue
            runner_up = _runner_up_score(scored, best.surface.id)
            if best.score - runner_up < self._margin:
                return CommandResolution(
                    CommandResolutionDecision.ABSTAINED,
                    surface=best.surface,
                    matched_alias=best.matched_alias,
                    score=best.score,
                )
            return CommandResolution(
                CommandResolutionDecision.RESOLVED,
                surface=best.surface,
                matched_alias=best.matched_alias,
                score=best.score,
            )

        best_overall = scored[0]
        if best_overall.score >= self._low:
            return CommandResolution(
                CommandResolutionDecision.ABSTAINED,
                surface=best_overall.surface,
                matched_alias=best_overall.matched_alias,
                score=best_overall.score,
            )
        return CommandResolution(
            CommandResolutionDecision.RAW,
            surface=best_overall.surface,
            matched_alias=best_overall.matched_alias,
            score=best_overall.score,
        )

    def _exact_matches(self, query: str) -> list[_SurfaceScore]:
        matches: list[_SurfaceScore] = []
        for surface in self._surfaces:
            for alias in surface.all_phrases():
                if _normalize(alias) == query:
                    matches.append(_SurfaceScore(surface, alias, 100.0))
                    break
        return matches

    def _resolve_exact(self, matches: Sequence[_SurfaceScore]) -> CommandResolution:
        for kind in (DispatchTargetKind.VAICOM_F10_ACTION, DispatchTargetKind.VOICEATTACK):
            same_kind = [match for match in matches if _target_kind(match.surface) is kind]
            if not same_kind:
                continue
            ids = {match.surface.id for match in same_kind}
            if len(ids) > 1:
                best = same_kind[0]
                return CommandResolution(
                    CommandResolutionDecision.ABSTAINED,
                    surface=best.surface,
                    matched_alias=best.matched_alias,
                    score=100.0,
                )
            best = same_kind[0]
            return CommandResolution(
                CommandResolutionDecision.RESOLVED,
                surface=best.surface,
                matched_alias=best.matched_alias,
                score=100.0,
            )
        return CommandResolution(CommandResolutionDecision.RAW)

    def _score_surfaces(self, query: str) -> tuple[_SurfaceScore, ...]:
        best_by_surface: dict[str, _SurfaceScore] = {}
        for surface in self._surfaces:
            for alias in surface.all_phrases():
                score = _score(query, _normalize(alias), surface)
                current = best_by_surface.get(surface.id)
                if current is None or score > current.score:
                    best_by_surface[surface.id] = _SurfaceScore(surface, alias, score)
        return tuple(
            sorted(
                best_by_surface.values(),
                key=lambda item: (item.score, _priority(item.surface)),
                reverse=True,
            )
        )


def _best_for_kind(
    scored: Sequence[_SurfaceScore], kind: DispatchTargetKind
) -> _SurfaceScore | None:
    for item in scored:
        if _target_kind(item.surface) is kind:
            return item
    return None


def _runner_up_score(scored: Sequence[_SurfaceScore], best_id: str) -> float:
    for item in scored:
        if item.surface.id != best_id:
            return item.score
    return 0.0


def _priority(surface: CommandSurface) -> int:
    kind = _target_kind(surface)
    if kind is DispatchTargetKind.VAICOM_F10_ACTION:
        return 2
    return 1


def _target_kind(surface: CommandSurface) -> DispatchTargetKind:
    return surface.dispatch_target.target_kind


def _normalize(text: str) -> str:
    """Normalize a surface phrase for matching."""
    return " ".join(_PUNCTUATION.sub(" ", text.casefold()).split())


def _score(query: str, choice: str, surface: CommandSurface) -> float:
    score = fuzz.token_sort_ratio(query, choice)
    if isinstance(surface.dispatch_target, VaicomF10Action):
        # VAICOM-compatible missions often display full radio prompts where the live F10
        # label is embedded near the end. Token-set scoring lets "Clearance ... FLEX NORTH"
        # resolve to the active "FLEX NORTH" action while the runner-up margin still
        # protects against similarly named menu items.
        score = max(score, fuzz.token_set_ratio(query, choice))
    return float(score)
