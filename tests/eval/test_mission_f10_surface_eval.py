"""Typed mission-F10 evaluation against realistic live-menu distractors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.eval.harness import load_vocab
from vaivox.domain.commands.model import (
    CommandResolutionDecision,
    CommandSurface,
    VaicomF10Action,
)
from vaivox.domain.commands.resolver import CommandSurfaceResolver
from vaivox.domain.reconciliation.pipeline import reconcile

_FIXTURES = Path(__file__).parent / "fixtures"
_SEMANTIC_ALIASES = {
    "Request Engine Start": (
        "Engine Start",
        "Request To Start Engines",
        "Requesting Start",
    ),
    "Request Takeoff": (
        "Ready at the Hold",
        "Ready in turn",
        "Requesting Takeoff Clearance",
    ),
    "Request Taxi to Runway": (
        "Request Taxi for Takeoff",
        "Request Taxi for Departure",
        "Request Taxi Clearance",
    ),
}


def _load_cases() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (_FIXTURES / "mission_f10_surface_cases.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _load_live_menu() -> list[CommandSurface]:
    labels = [
        line.strip()
        for line in (_FIXTURES / "mission_f10_live_menu.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return [
        CommandSurface(
            id=f"mission_f10:{index}",
            label=label,
            aliases=(f"Action {label}",),
            source="mission_f10",
            scope="AI ATC Nellis AFB",
            dispatch_target=VaicomF10Action(
                identifier=f"Action {label}",
                label=label,
                command_id=20_000 + index,
                action_index=index,
            ),
            semantic_aliases=_SEMANTIC_ALIASES.get(label, ()),
        )
        for index, label in enumerate(labels)
    ]


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: str(case["raw_stt"]))
def test_real_calls_resolve_to_the_expected_typed_f10_surface(
    case: dict[str, object],
) -> None:
    vocab = load_vocab()
    result = reconcile(
        str(case["raw_stt"]),
        vocab["word_mappings"],
        vocab["fuzzy_words"],
        vocab["phonetic_alphabet"],
    )
    resolution = CommandSurfaceResolver(_load_live_menu()).resolve(result.command_text)

    assert resolution.decision is CommandResolutionDecision.RESOLVED
    assert resolution.surface is not None
    assert resolution.surface.label == case["expected_label"]
    assert isinstance(resolution.surface.dispatch_target, VaicomF10Action)
