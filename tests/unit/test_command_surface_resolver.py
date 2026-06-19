"""Unit tests for typed command-surface resolution."""

from __future__ import annotations

from vaivox.domain.commands.model import (
    CommandResolutionDecision,
    CommandSurface,
    VaicomF10Action,
    VoiceAttackCommand,
)
from vaivox.domain.commands.resolver import CommandSurfaceResolver


def _voiceattack(label: str) -> CommandSurface:
    return CommandSurface(
        id=f"voiceattack:{label.casefold().replace(' ', '-')}",
        label=label,
        aliases=(),
        source="voiceattack",
        scope="global",
        dispatch_target=VoiceAttackCommand(label),
    )


def _f10(label: str, identifier: str | None = None) -> CommandSurface:
    identifier = identifier or f"Action {label}"
    return CommandSurface(
        id=f"mission_f10:{identifier.casefold().replace(' ', '-')}",
        label=label,
        aliases=(identifier, f"Request a {label}"),
        source="mission_f10",
        scope="mission",
        dispatch_target=VaicomF10Action(
            identifier=identifier,
            label=label,
            command_id=20042,
            action_index=3,
        ),
    )


def test_flex_north_resolves_to_f10_not_voiceattack() -> None:
    resolver = CommandSurfaceResolver([_voiceattack("FLEX NORTH"), _f10("FLEX NORTH")])

    resolution = resolver.resolve("FLEX NORTH")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert isinstance(resolution.surface.dispatch_target, VaicomF10Action)
    assert resolution.surface.dispatch_target.identifier == "Action FLEX NORTH"


def test_action_identifier_is_a_diagnostic_alias_not_a_voiceattack_command() -> None:
    resolver = CommandSurfaceResolver([_voiceattack("Action FLEX NORTH"), _f10("FLEX NORTH")])

    resolution = resolver.resolve("Action FLEX NORTH")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert isinstance(resolution.surface.dispatch_target, VaicomF10Action)
    assert resolution.matched_alias == "Action FLEX NORTH"


def test_request_alias_resolves_to_f10_action() -> None:
    resolver = CommandSurfaceResolver([_f10("FLEX NORTH")])

    resolution = resolver.resolve("Request a FLEX NORTH")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert isinstance(resolution.surface.dispatch_target, VaicomF10Action)


def test_long_ai_atc_prompt_resolves_to_embedded_f10_action() -> None:
    resolver = CommandSurfaceResolver([_f10("FLEX NORTH")])

    resolution = resolver.resolve("Clearance delivery Uzi61 Clearance on Request VFR FLEX NORTH")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert isinstance(resolution.surface.dispatch_target, VaicomF10Action)
    assert resolution.surface.dispatch_target.identifier == "Action FLEX NORTH"


def test_static_command_resolves_to_voiceattack_command() -> None:
    resolver = CommandSurfaceResolver([_voiceattack("Texaco request rejoin")])

    resolution = resolver.resolve("Texaco request rejoin")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert isinstance(resolution.surface.dispatch_target, VoiceAttackCommand)
    assert resolution.surface.dispatch_target.command_name == "Texaco request rejoin"


def test_ambiguous_surfaces_abstain_without_typed_dispatch() -> None:
    resolver = CommandSurfaceResolver(
        [_f10("FLEX NORTH", "Action FLEX NORTH A"), _f10("FLEX NORTH", "Action FLEX NORTH B")]
    )

    resolution = resolver.resolve("FLEX NORTH")

    assert resolution.decision is CommandResolutionDecision.ABSTAINED
    assert resolution.score == 100.0
