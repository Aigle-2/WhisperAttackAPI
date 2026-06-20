"""Unit tests for typed dispatch: static commands vs live VAICOM F10 actions (ADR-0012)."""

from __future__ import annotations

import pytest

from vaivox.domain.commands.model import (
    DispatchOutcome,
    DispatchTargetKind,
    VaicomF10Action,
    VoiceAttackCommand,
)
from vaivox.domain.telemetry.model import MatchOutcome
from vaivox.infrastructure.voiceattack.dispatcher import TypedCommandDispatcher


class FakeCommandSink:
    def __init__(self, outcome: MatchOutcome | None) -> None:
        self.outcome = outcome
        self.sent: list[str] = []

    def send(self, command: str) -> MatchOutcome | None:
        self.sent.append(command)
        return self.outcome


class FakeF10Sink:
    def __init__(self, outcome: DispatchOutcome) -> None:
        self.outcome = outcome
        self.dispatched: list[VaicomF10Action] = []

    def dispatch(self, action: VaicomF10Action) -> DispatchOutcome:
        self.dispatched.append(action)
        return self.outcome


def _f10_action(action_index: int | None = 0) -> VaicomF10Action:
    return VaicomF10Action(
        identifier="Action FLEX NORTH",
        label="FLEX NORTH",
        command_id=20086,
        action_index=action_index,
    )


def _accepted_f10_outcome() -> DispatchOutcome:
    return DispatchOutcome(
        target_kind=DispatchTargetKind.VAICOM_F10_ACTION.value,
        accepted=True,
        resolved_target="Action FLEX NORTH",
        detail="DCS doAction actionIndex 0 via mission.player.actionsequence",
    )


def test_static_command_sends_its_exact_name_to_voiceattack() -> None:
    match = MatchOutcome(matched=True, resolved_command="Kobuleti tower")
    voiceattack = FakeCommandSink(match)
    f10 = FakeF10Sink(_accepted_f10_outcome())

    result = TypedCommandDispatcher(voiceattack, f10).dispatch(VoiceAttackCommand("Kobuleti tower"))

    assert voiceattack.sent == ["Kobuleti tower"]
    assert f10.dispatched == []
    assert result.match == match
    assert result.dispatch.target_kind == DispatchTargetKind.VOICEATTACK.value
    assert result.dispatch.accepted is True


def test_f10_action_routes_to_the_f10_sink_not_voiceattack() -> None:
    # F10 items are not VoiceAttack commands: they must never hit the command profile.
    voiceattack = FakeCommandSink(MatchOutcome(matched=False))
    f10 = FakeF10Sink(_accepted_f10_outcome())
    action = _f10_action()

    result = TypedCommandDispatcher(voiceattack, f10).dispatch(action)

    assert voiceattack.sent == []
    assert f10.dispatched == [action]
    assert result.match is None  # UDP doAction is fire-and-forget: no return channel
    assert result.dispatch.target_kind == DispatchTargetKind.VAICOM_F10_ACTION.value
    assert result.dispatch.accepted is True
    assert result.dispatch.resolved_target == "Action FLEX NORTH"


def test_f10_action_propagates_sink_rejection() -> None:
    rejected = DispatchOutcome(
        target_kind=DispatchTargetKind.VAICOM_F10_ACTION.value,
        accepted=False,
        resolved_target="Action FLEX NORTH",
        detail="no live ActionIndex available",
    )
    f10 = FakeF10Sink(rejected)

    dispatcher = TypedCommandDispatcher(FakeCommandSink(None), f10)
    result = dispatcher.dispatch(_f10_action(action_index=None))

    assert result.dispatch.accepted is False
    assert result.match is None


def test_unsupported_target_raises() -> None:
    dispatcher = TypedCommandDispatcher(FakeCommandSink(None), FakeF10Sink(_accepted_f10_outcome()))
    with pytest.raises(TypeError):
        dispatcher.dispatch("not a target")  # type: ignore[arg-type]
