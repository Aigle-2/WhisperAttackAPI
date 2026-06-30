"""Tests for generic VoiceAttack dynamic command-pattern resolution."""

from __future__ import annotations

from vaivox.domain.commands.model import (
    CommandResolutionDecision,
    CommandSurface,
    VoiceAttackCommand,
)
from vaivox.domain.commands.resolver import CommandSurfaceResolver
from vaivox.infrastructure.voiceattack.dynamic_patterns import (
    VoiceAttackDynamicCommandMatcher,
    format_voiceattack_pattern,
    voiceattack_pattern_matches,
)


def _surface(pattern: str, *, scope: str = "global") -> CommandSurface:
    return CommandSurface(
        id=f"voiceattack:{pattern.casefold()}",
        label=pattern,
        aliases=(),
        source="voiceattack",
        scope=scope,
        dispatch_target=VoiceAttackCommand(pattern),
    )


def test_f4_tacan_channel_uses_profile_pattern_not_static_exception() -> None:
    matcher = VoiceAttackDynamicCommandMatcher(
        CommandSurfaceResolver(
            [
                _surface(
                    "[WSO; Wizzo; Boots;] [Set; Select] TACAN [channel] "
                    "[zero;0;1] [0..9] [0..9] [X-ray; Yankee]",
                    scope="F-4E",
                )
            ]
        ),
        lambda: "F-4E-45MC",
    )

    resolution = matcher.resolve("Set TACAN 96")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.surface is not None
    assert resolution.surface.dispatch_target.command_name == "Set TACAN channel 0 9 6 X-ray"


def test_missing_literals_and_choices_can_be_completed_from_the_same_pattern() -> None:
    matcher = VoiceAttackDynamicCommandMatcher(
        CommandSurfaceResolver(
            [
                _surface(
                    "[WSO; Wizzo; Boots;] [Set; Select] TACAN [channel] "
                    "[zero;0;1] [0..9] [0..9] [X-ray; Yankee]",
                    scope="F-4E",
                )
            ]
        ),
        lambda: "F-4E-45MC",
    )

    resolution = matcher.resolve("Tune TACAN one two")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.surface is not None
    assert resolution.surface.dispatch_target.command_name == "Set TACAN channel 0 1 2 X-ray"


def test_dynamic_pattern_matching_is_generic_for_other_numeric_ranges() -> None:
    matcher = VoiceAttackDynamicCommandMatcher(
        CommandSurfaceResolver(
            [_surface("[WSO; Wizzo; Boots;] Radar Focus Target [1..20]", scope="F-4E")]
        ),
        lambda: "F-4E-45MC",
    )

    resolution = matcher.resolve("Radar Focus Target 12")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.surface is not None
    assert resolution.surface.dispatch_target.command_name == "Radar Focus Target 12"


def test_current_aircraft_scope_wins_over_a_global_dynamic_pattern() -> None:
    matcher = VoiceAttackDynamicCommandMatcher(
        CommandSurfaceResolver(
            [
                _surface("TACAN Tune [X-Ray;Yankee] [0..1] [0..9] [0..9]"),
                _surface(
                    "[WSO; Wizzo; Boots;] [Set; Select] TACAN [channel] "
                    "[zero;0;1] [0..9] [0..9] [X-ray; Yankee]",
                    scope="F-4E",
                ),
            ]
        ),
        lambda: "F-4E-45MC",
    )

    resolution = matcher.resolve("Tune TACAN 12")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.surface is not None
    assert resolution.surface.scope == "F-4E"
    assert resolution.surface.dispatch_target.command_name == "Set TACAN channel 0 1 2 X-ray"


def test_other_aircraft_specific_patterns_are_ignored_when_aircraft_is_known() -> None:
    matcher = VoiceAttackDynamicCommandMatcher(
        CommandSurfaceResolver(
            [_surface("TACAN Tune [X-Ray;Yankee] [0..1] [0..9] [0..9]", scope="F-14")]
        ),
        lambda: "F-4E-45MC",
    )

    resolution = matcher.resolve("TACAN tune 12")

    assert resolution.decision is not CommandResolutionDecision.RESOLVED


def test_format_voiceattack_pattern_humanizes_f4_tacan_channel() -> None:
    pattern = (
        "[WSO; Wizzo; Boots;] [Set; Select] TACAN [channel] "
        "[zero;0;1] [0..9] [0..9] [X-ray; Yankee]"
    )

    assert format_voiceattack_pattern(pattern) == "Set/Select TACAN channel <000-199> X-ray/Yankee"


def test_format_voiceattack_pattern_humanizes_generic_numeric_range() -> None:
    assert (
        format_voiceattack_pattern("[WSO; Wizzo; Boots;] Radar Focus Target [1..20]")
        == "Radar Focus Target <1-20>"
    )


def test_format_voiceattack_pattern_marks_optional_slots() -> None:
    assert (
        format_voiceattack_pattern("[Deactivate;] [Hold; Hold at] waypoint [1..9]")
        == "(Deactivate) Hold/Hold at waypoint <1-9>"
    )


def test_format_voiceattack_pattern_compresses_repeated_phonetic_letter_slots() -> None:
    alphabet = ";".join(
        (
            "Alpha",
            "Bravo",
            "Charlie",
            "Delta",
            "Echo",
            "Foxtrot",
            "Golf",
            "Hotel",
            "India",
            "Juliet",
            "Kilo",
            "Lima",
            "Mike",
            "November",
            "Oscar",
            "Papa",
            "Quebec",
            "Romeo",
            "Sierra",
            "Tango",
            "Uniform",
            "Victor",
            "Whiskey",
            "X-Ray",
            "Yankee",
            "Zulu",
        )
    )
    pattern = (
        f"[WSO; Wizzo; Boots;] [Set; Tune] TACAN station [{alphabet}] [{alphabet}] [{alphabet}]"
    )

    assert format_voiceattack_pattern(pattern) == "Set/Tune TACAN station <3 letters>"


def test_voiceattack_pattern_matches_concrete_search_query() -> None:
    pattern = (
        "[WSO; Wizzo; Boots;] [Set; Select] TACAN [channel] "
        "[zero;0;1] [0..9] [0..9] [X-ray; Yankee]"
    )

    assert voiceattack_pattern_matches(pattern, "tacan 96")
    assert voiceattack_pattern_matches(pattern, "tacan one two")
    assert not voiceattack_pattern_matches(pattern, "ground power")
