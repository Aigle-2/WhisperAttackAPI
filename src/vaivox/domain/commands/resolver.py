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
_CALLSIGN_PREFIXES = (
    ("set", "call", "sign"),
    ("set", "callsign"),
    ("sets", "call", "sign"),
    ("sets", "callsign"),
)
_DIGIT_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "niner": "9",
}
_COMBINED_CALLSIGN_REASON = (
    "AI_ATC exposes separate callsign-name and digit actions but no safe atomic combined "
    "action; set the name or digit separately"
)


@dataclass(frozen=True)
class _SurfaceScore:
    surface: CommandSurface
    matched_alias: str
    score: float


class CommandSurfaceResolver:
    """Resolve text against a frozen command-surface index.

    Exact matches are resolved before fuzzy matches, with active mission F10 actions
    taking priority over static VoiceAttack commands. Multi-token F10 labels may also
    resolve through the anchored ``set call sign <label>`` grammar or when embedded
    contiguously in a longer radio call; the most specific unique label wins. Fuzzy matches
    use the same conservative high/low/margin thresholds as phrase snap, and abstain when
    the best match is too close to the runner-up.
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

        combined = self._combined_callsign_rejection(query)
        if combined is not None:
            return combined

        exact = self._exact_matches(query)
        if exact:
            return self._resolve_exact(exact)

        callsign = self._anchored_callsign_matches(query)
        if callsign:
            return self._resolve_exact(callsign)

        embedded = self._embedded_label_matches(query)
        if embedded:
            return self._resolve_embedded(embedded, query)

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
            return _resolved_or_rejected(best)

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
            available = [match for match in same_kind if match.surface.available]
            if available:
                same_kind = available
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
            return _resolved_or_rejected(best)
        return CommandResolution(CommandResolutionDecision.RAW)

    def _combined_callsign_rejection(self, query: str) -> CommandResolution | None:
        """Reject ``set callsign <name> <digits>`` before any legacy fallback."""
        remainder = _callsign_remainder(query)
        if remainder is None or len(remainder) < 2:
            return None
        for split in range(1, len(remainder)):
            name = " ".join(remainder[:split])
            digits = remainder[split:]
            if not all(_is_callsign_number_token(token) for token in digits):
                continue
            surface = next(
                (
                    candidate
                    for candidate in self._surfaces
                    if isinstance(candidate.dispatch_target, VaicomF10Action)
                    and any(character.isalpha() for character in candidate.label)
                    and _normalize(candidate.label) == name
                ),
                None,
            )
            if surface is not None:
                return CommandResolution(
                    CommandResolutionDecision.REJECTED,
                    surface=surface,
                    matched_alias=surface.label,
                    score=100.0,
                    reason_code="combined_callsign_unsupported",
                    reason=_COMBINED_CALLSIGN_REASON,
                )
        return None

    def _anchored_callsign_matches(self, query: str) -> list[_SurfaceScore]:
        """Match ``set call sign|callsign <label>`` to an exact F10 label."""
        remainder = _callsign_remainder(query)
        if remainder is None:
            return []
        requested = _callsign_requested_label(remainder)
        if requested is None:
            return []
        requested_label, requires_digit_surface = requested
        return [
            _SurfaceScore(surface, surface.label, 100.0)
            for surface in self._surfaces
            if isinstance(surface.dispatch_target, VaicomF10Action)
            and _normalize(surface.label) == requested_label
            and (not requires_digit_surface or _is_callsign_digit_surface(surface))
        ]

    def _embedded_label_matches(self, query: str) -> list[_SurfaceScore]:
        """Find multi-token F10 labels embedded contiguously in ``query``."""
        query_tokens = tuple(query.split())
        matches: list[_SurfaceScore] = []
        for surface in self._surfaces:
            if not isinstance(surface.dispatch_target, VaicomF10Action):
                continue
            for phrase in surface.embedded_phrases():
                phrase_tokens = tuple(_normalize(phrase).split())
                if len(phrase_tokens) < 2:
                    continue
                if _contains_contiguous_tokens(query_tokens, phrase_tokens):
                    matches.append(_SurfaceScore(surface, phrase, 100.0))
        return matches

    def _resolve_embedded(self, matches: Sequence[_SurfaceScore], query: str) -> CommandResolution:
        """Resolve the unique most-specific embedded label, or fail closed."""
        specificity = max(_embedded_specificity(match) for match in matches)
        most_specific = [match for match in matches if _embedded_specificity(match) == specificity]
        available = [match for match in most_specific if match.surface.available]
        if available:
            most_specific = available
        if len({match.surface.id for match in most_specific}) > 1:
            context_scores = {
                match.surface.id: _path_context_score(query, match.surface)
                for match in most_specific
            }
            best_context = max(context_scores.values())
            if best_context > 0:
                most_specific = [
                    match
                    for match in most_specific
                    if context_scores[match.surface.id] == best_context
                ]
        best = most_specific[0]
        if len({match.surface.id for match in most_specific}) > 1:
            return CommandResolution(
                CommandResolutionDecision.ABSTAINED,
                surface=best.surface,
                matched_alias=best.matched_alias,
                score=100.0,
            )
        return _resolved_or_rejected(best)

    def _score_surfaces(self, query: str) -> tuple[_SurfaceScore, ...]:
        best_by_surface: dict[str, _SurfaceScore] = {}
        for surface in self._surfaces:
            if (
                isinstance(surface.dispatch_target, VaicomF10Action)
                and len(_normalize(surface.label).split()) < 2
            ):
                # Single-token live menu entries (especially callsigns and digits) are
                # too weak to infer from surrounding speech. They remain available via
                # the whole-query exact phase above.
                continue
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


def _embedded_specificity(match: _SurfaceScore) -> tuple[int, int]:
    phrase = _normalize(match.matched_alias)
    return len(phrase.split()), len(phrase)


def _path_context_score(query: str, surface: CommandSurface) -> int:
    target = surface.dispatch_target
    if not isinstance(target, VaicomF10Action):
        return 0
    query_tokens = set(query.split())
    path_tokens = set(_normalize(" ".join(target.menu_path)).split())
    return len(query_tokens & path_tokens)


def _resolved_or_rejected(match: _SurfaceScore) -> CommandResolution:
    surface = match.surface
    if not surface.available:
        return CommandResolution(
            CommandResolutionDecision.REJECTED,
            surface=surface,
            matched_alias=match.matched_alias,
            score=match.score,
            reason_code="mission_action_inactive",
            reason=surface.unavailable_reason or "mission action is not currently available",
        )
    return CommandResolution(
        CommandResolutionDecision.RESOLVED,
        surface=surface,
        matched_alias=match.matched_alias,
        score=match.score,
    )


def _callsign_remainder(query: str) -> tuple[str, ...] | None:
    tokens = tuple(query.split())
    for prefix in _CALLSIGN_PREFIXES:
        if tokens[: len(prefix)] == prefix:
            remainder = tokens[len(prefix) :]
            return remainder or None
    return None


def _callsign_requested_label(remainder: tuple[str, ...]) -> tuple[str, bool] | None:
    """Return the live F10 label requested by an anchored callsign phrase.

    AI_ATC's ``Set Integer`` menu exposes only one digit leaf per flight number. Operators
    still naturally say their full DCS callsign number (for example ``13``); route that to
    the leading digit leaf while keeping generic embedded digit matching disabled.
    """
    if remainder[:1] in (("digit",), ("digits",)):
        remainder = remainder[1:]
    if not remainder:
        return None

    number = _callsign_number_digits(remainder)
    if number is not None:
        return number[0], True

    if not any(token.isalpha() for token in remainder):
        return None
    return " ".join(remainder), False


def _callsign_number_digits(tokens: tuple[str, ...]) -> str | None:
    digits: list[str] = []
    for token in tokens:
        normalized = _normalize(token)
        if normalized.isdigit() and len(normalized) <= 2:
            digits.append(normalized)
            continue
        digit = _DIGIT_WORDS.get(normalized)
        if digit is None:
            return None
        digits.append(digit)
    joined = "".join(digits)
    if 1 <= len(joined) <= 2:
        return joined
    return None


def _is_callsign_number_token(token: str) -> bool:
    normalized = _normalize(token)
    return (normalized.isdigit() and len(normalized) <= 2) or normalized in _DIGIT_WORDS


def _is_callsign_digit_surface(surface: CommandSurface) -> bool:
    target = surface.dispatch_target
    if not isinstance(target, VaicomF10Action):
        return False
    if not target.menu_path:
        return True
    path = _normalize(" ".join(target.menu_path))
    return "set integer" in path or "set callsign" in path or "set call sign" in path


def _contains_contiguous_tokens(query_tokens: Sequence[str], label_tokens: Sequence[str]) -> bool:
    width = len(label_tokens)
    return any(
        tuple(query_tokens[start : start + width]) == tuple(label_tokens)
        for start in range(len(query_tokens) - width + 1)
    )


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
