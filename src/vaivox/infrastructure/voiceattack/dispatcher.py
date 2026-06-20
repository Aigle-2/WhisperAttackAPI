"""Dispatch typed command targets through their concrete adapters (ADR-0012).

Static VoiceAttack commands go to the VoiceAttack command sink — exact-name dispatch with
the plugin return channel (ADR-0006). Live VAICOM F10 actions go to the
:class:`~vaivox.application.ports.VaicomF10ActionSink`, which fires DCS's ``doAction`` over
UDP: VAICOM does not register F10 menu items as VoiceAttack commands, so they must take
this separate transport rather than the command profile.
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
    """Dispatch typed command targets through their matching adapter."""

    def __init__(self, voiceattack: CommandSink, vaicom_f10: VaicomF10ActionSink) -> None:
        """Wire the static VoiceAttack sink and the VAICOM F10 action sink."""
        self._voiceattack = voiceattack
        self._vaicom_f10 = vaicom_f10

    def dispatch(self, target: DispatchTarget) -> CommandDispatchResult:
        """Dispatch ``target`` through the adapter matching its target kind."""
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

        raise TypeError(f"Unsupported dispatch target: {type(target).__name__}")
