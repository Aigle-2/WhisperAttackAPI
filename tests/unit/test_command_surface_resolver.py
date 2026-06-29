"""Unit tests for typed command-surface resolution."""

from __future__ import annotations

import pytest

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


def _f10(
    label: str,
    identifier: str | None = None,
    menu_path: tuple[str, ...] = (),
) -> CommandSurface:
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
            menu_path=menu_path,
        ),
    )


def _live_like_f10_menu() -> list[CommandSurface]:
    labels = [
        "DREAM 7",
        "FYTTR 7",
        "MORMON MESA 8",
        "FLEX NORTH",
        "FLEX WEST",
        "Request Engine Start",
        "Lion",
        "Chaos",
        *(str(digit) for digit in range(10)),
    ]
    return [_f10(label) for label in labels]


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


def test_long_ai_atc_prompt_resolves_to_embedded_f10_action_with_numeric_distractors() -> None:
    resolver = CommandSurfaceResolver(_live_like_f10_menu())

    resolution = resolver.resolve("Clearance delivery Uzi61 Clearance on Request VFR FLEX NORTH")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert isinstance(resolution.surface.dispatch_target, VaicomF10Action)
    assert resolution.surface.dispatch_target.identifier == "Action FLEX NORTH"


@pytest.mark.parametrize(
    "transcript",
    [
        "Clearance Lion 6-1 Clearance on request IFR DREAM 7",
        "Clearance delivery Lion 61 Clearance on request IFR DREAM 7",
    ],
)
def test_real_clearance_calls_resolve_dream_7_with_numeric_distractors(
    transcript: str,
) -> None:
    resolver = CommandSurfaceResolver(_live_like_f10_menu())

    resolution = resolver.resolve(transcript)

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.surface is not None
    assert resolution.surface.label == "DREAM 7"
    assert resolution.matched_alias == "DREAM 7"


def test_long_engine_start_call_resolves_with_numeric_distractors() -> None:
    resolver = CommandSurfaceResolver(_live_like_f10_menu())

    resolution = resolver.resolve("Ground Lion 6 1 request engine start")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.surface is not None
    assert resolution.surface.label == "Request Engine Start"


def test_bare_digit_still_resolves_as_an_exact_f10_command() -> None:
    resolver = CommandSurfaceResolver(_live_like_f10_menu())

    resolution = resolver.resolve("7")

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.surface is not None
    assert resolution.surface.label == "7"


@pytest.mark.parametrize(
    "query",
    [
        "Set call sign Chaos",
        "Set callsign Chaos",
        "Sets call sign Chaos",
        "Sets callsign Chaos",
    ],
)
def test_anchored_callsign_phrase_resolves_a_single_token_f10_label(query: str) -> None:
    resolver = CommandSurfaceResolver(_live_like_f10_menu())

    resolution = resolver.resolve(query)

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.surface is not None
    assert resolution.surface.label == "Chaos"
    assert resolution.matched_alias == "Chaos"


@pytest.mark.parametrize(
    "query",
    [
        "Approach report callsign Chaos",
    ],
)
def test_callsign_grammar_rejects_unanchored_phrases(query: str) -> None:
    resolver = CommandSurfaceResolver(_live_like_f10_menu())

    resolution = resolver.resolve(query)

    assert resolution.decision is not CommandResolutionDecision.RESOLVED


@pytest.mark.parametrize("query", ["Set callsign 7", "Set callsign digit seven"])
def test_callsign_digit_grammar_resolves_an_exact_numeric_leaf(query: str) -> None:
    resolver = CommandSurfaceResolver(_live_like_f10_menu())

    resolution = resolver.resolve(query)

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.surface is not None
    assert resolution.surface.label == "7"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Set call sign 13", "1"),
        ("Set callsign 1 3", "1"),
        ("Set callsign one three", "1"),
        ("Set callsign 61", "6"),
    ],
)
def test_callsign_number_uses_the_ai_atc_set_integer_leaf(
    query: str,
    expected: str,
) -> None:
    resolver = CommandSurfaceResolver(_live_like_f10_menu())

    resolution = resolver.resolve(query)

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.surface is not None
    assert resolution.surface.label == expected


def test_callsign_number_does_not_resolve_an_unrelated_numeric_surface() -> None:
    resolver = CommandSurfaceResolver([_f10("13", menu_path=("Runway",))])

    resolution = resolver.resolve("Set callsign 13")

    assert resolution.decision is not CommandResolutionDecision.RESOLVED


@pytest.mark.parametrize("query", ["Set call sign Chaos 1-1", "Set callsign Chaos 11"])
def test_combined_callsign_is_terminally_rejected(query: str) -> None:
    resolver = CommandSurfaceResolver(_live_like_f10_menu())

    resolution = resolver.resolve(query)

    assert resolution.decision is CommandResolutionDecision.REJECTED
    assert resolution.reason_code == "combined_callsign_unsupported"


def test_anchored_callsign_phrase_abstains_on_duplicate_live_labels() -> None:
    resolver = CommandSurfaceResolver(
        [_f10("Chaos", "Action Chaos A"), _f10("Chaos", "Action Chaos B")]
    )

    resolution = resolver.resolve("Set call sign Chaos")

    assert resolution.decision is CommandResolutionDecision.ABSTAINED
    assert resolution.score == 100.0


def test_digit_embedded_in_unrelated_speech_never_resolves() -> None:
    resolver = CommandSurfaceResolver(_live_like_f10_menu())

    resolution = resolver.resolve("Lion 6 1 check radio 7")

    assert resolution.decision is not CommandResolutionDecision.RESOLVED


def test_equally_specific_embedded_labels_abstain() -> None:
    resolver = CommandSurfaceResolver([_f10("DREAM 7"), _f10("FYTTR 7")])

    resolution = resolver.resolve("Clearance request DREAM 7 or FYTTR 7")

    assert resolution.decision is CommandResolutionDecision.ABSTAINED
    assert resolution.score == 100.0


def test_diagnostic_alias_is_not_used_for_embedded_matching() -> None:
    resolver = CommandSurfaceResolver([_f10("NORTH", identifier="Action FLEX NORTH")])

    resolution = resolver.resolve("Clearance request Action FLEX NORTH now")

    assert resolution.decision is CommandResolutionDecision.RAW


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
