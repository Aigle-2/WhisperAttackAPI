"""Typed command dispatcher adapters.

The application routes typed dispatch targets; this infrastructure adapter delegates
static VoiceAttack commands to the existing socket sink and keeps VAICOM F10 execution
behind an explicit action sink.
"""

from __future__ import annotations

from vaivox.application.ports import CommandDispatchResult, CommandSink, VaicomF10ActionSink
from vaivox.domain.commands.model import (
    DispatchOutcome,
    DispatchTarget,
    DispatchTargetKind,
    VaicomF10Action,
    VoiceAttackCommand,
)


class TypedCommandDispatcher:
    """Dispatch typed command targets through their concrete adapters."""

    def __init__(
        self,
        voiceattack: CommandSink,
        vaicom_f10: VaicomF10ActionSink,
    ) -> None:
        """Wire the static VoiceAttack sink and the VAICOM F10 action sink."""
        self._voiceattack = voiceattack
        self._vaicom_f10 = vaicom_f10

    def dispatch(self, target: DispatchTarget) -> CommandDispatchResult:
        """Dispatch ``target`` through the matching adapter."""
        if isinstance(target, VoiceAttackCommand):
            match = self._voiceattack.send(target.command_name)
            accepted = True if match is None else match.matched
            return CommandDispatchResult(
                dispatch=DispatchOutcome(
                    target_kind=DispatchTargetKind.VOICEATTACK.value,
                    accepted=accepted,
                    resolved_target=target.command_name,
                    detail="VoiceAttack exact-name command",
                ),
                match=match,
            )
        if isinstance(target, VaicomF10Action):
            return CommandDispatchResult(dispatch=self._vaicom_f10.dispatch(target))


class DisabledVaicomF10ActionSink:
    """Safe default F10 sink until the VAICOM/DCS actionsequence smoke test is complete."""

    def dispatch(self, action: VaicomF10Action) -> DispatchOutcome:
        """Report the F10 action as recognized but not executed."""
        return DispatchOutcome(
            target_kind=DispatchTargetKind.VAICOM_F10_ACTION.value,
            accepted=False,
            resolved_target=action.identifier,
            detail="VAICOM F10 typed dispatch is disabled pending DCS smoke validation",
        )
