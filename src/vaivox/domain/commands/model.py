"""Pure command-surface value objects.

VAIVOX recognizes spoken text, but it should not treat the recognized string as the
execution contract. A spoken surface resolves to a typed dispatch target: a static
VoiceAttack command, a live VAICOM F10 action, or another typed target added later.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DispatchTargetKind(StrEnum):
    """The concrete dispatch mechanism a resolved surface targets."""

    VOICEATTACK = "voiceattack"
    VAICOM_F10_ACTION = "vaicom_f10_action"


@dataclass(frozen=True)
class VoiceAttackCommand:
    """A static VoiceAttack command dispatched by exact command name."""

    command_name: str

    @property
    def target_kind(self) -> DispatchTargetKind:
        """The target kind used in telemetry and dispatch routing."""
        return DispatchTargetKind.VOICEATTACK


@dataclass(frozen=True)
class VaicomF10Action:
    """A live VAICOM-imported DCS F10 mission action.

    Attributes:
        identifier: VAICOM's internal F10 identifier, e.g. ``"Action FLEX NORTH"``.
        label: Human-facing menu label, e.g. ``"FLEX NORTH"``.
        command_id: VAICOM's generated command id from the log, when present.
        action_index: DCS/VAICOM action index from the imported menu item, when present.
    """

    identifier: str
    label: str
    command_id: int | None = None
    action_index: int | None = None

    @property
    def target_kind(self) -> DispatchTargetKind:
        """The target kind used in telemetry and dispatch routing."""
        return DispatchTargetKind.VAICOM_F10_ACTION


type DispatchTarget = VoiceAttackCommand | VaicomF10Action


@dataclass(frozen=True)
class CommandSurface:
    """One speakable surface bound to a typed dispatch target.

    Attributes:
        id: Stable id within the current command catalog.
        label: Canonical human-readable command label.
        aliases: Additional phrases that should resolve to the same target.
        source: Where the surface came from (``"voiceattack"`` / ``"mission_f10"``).
        scope: Surface lifetime/scope (``"global"`` / mission title / server scope).
        dispatch_target: The typed target the dispatcher will execute when resolved.
    """

    id: str
    label: str
    aliases: tuple[str, ...]
    source: str
    scope: str
    dispatch_target: DispatchTarget

    def all_phrases(self) -> tuple[str, ...]:
        """Return the label plus aliases, de-duplicated in order."""
        phrases: list[str] = []
        seen: set[str] = set()
        for phrase in (self.label, *self.aliases):
            normalized = " ".join(phrase.split()).casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            phrases.append(phrase)
        return tuple(phrases)


class CommandResolutionDecision(StrEnum):
    """How a reconciled utterance related to the command-surface catalog."""

    RESOLVED = "resolved"
    ABSTAINED = "abstained"
    RAW = "raw"


@dataclass(frozen=True)
class CommandResolution:
    """Result of resolving an utterance against command surfaces."""

    decision: CommandResolutionDecision
    surface: CommandSurface | None = None
    matched_alias: str | None = None
    score: float = 0.0


@dataclass(frozen=True)
class DispatchOutcome:
    """Typed dispatch result recorded after a target is handed to an adapter."""

    target_kind: str
    accepted: bool
    resolved_target: str | None = None
    detail: str | None = None
