# ADR-0012: Command surfaces and typed dispatch

**Status:** Accepted
**Date:** 2026-06-19
**Deciders:** Project owner (Aigle_2)

## Context

VAIVOX originally treated the reconciled utterance as the executable command string:
`reconcile(...) -> PhraseSnapper -> VoiceAttack Command.Exists/Execute(text)`.
That is valid for static VoiceAttack commands, but it is not the whole VAICOM model.

Mission F10 items imported by VAICOM are dynamic. The live log records entries such as
`Action FLEX NORTH`, with an `ActionIndex` and a `Command ID`. The human-facing menu
label is `FLEX NORTH`, but `Command.Exists("FLEX NORTH")` is not the execution contract
for that dynamic action. Treating the label as a static VoiceAttack command makes
VAIVOX fail on compatible VAICOM missions that expect VAICOM's dynamic F10 dispatch path.

## Decision

Model a spoken command as a **command surface** resolved to a **typed dispatch target**.
The recognized text is no longer assumed to be the executable string.

- `CommandSurface` is the pure domain object exposed by catalogs. It carries a label,
  aliases, source, scope, and a typed dispatch target.
- `VoiceAttackCommand(command_name)` is the target for static VoiceAttack commands.
  `Command.Exists/Execute` belongs only to this adapter path.
- `VaicomF10Action(identifier, label, command_id, action_index)` is the target for
  VAICOM-imported mission F10 actions. The identifier remains `Action ...`; the label is
  the human surface such as `FLEX NORTH`.
- `CommandSurfaceResolver` is pure domain logic. It resolves reconciled text against the
  live surface index with the conservative snap thresholds:
  exact mission F10, exact static, fuzzy mission F10, fuzzy static, then raw fallback.
  If two targets are too close, it abstains and no typed target is dispatched.
- `CommandDispatcher.dispatch(dispatch_target)` is the application port. It dispatches by
  target type and returns a `DispatchOutcome`. The legacy VoiceAttack sink remains as the
  adapter for `VoiceAttackCommand`.
- If no surface resolves, VAIVOX keeps the legacy fallback: phrase snap and dispatch the
  resulting text as a static `VoiceAttackCommand`.

Mission F10 dispatch is deliberately conservative at first. VAIVOX can resolve a live F10
surface and record the typed dispatch attempt, but the default `VaicomF10Action` adapter
refuses execution until the VAICOM/DCS smoke test validates the actual actionsequence
payload.

## Consequences

- Static VoiceAttack behavior stays compatible through `VoiceAttackCommand` and the raw
  fallback.
- Dynamic F10 mission commands are no longer polluted into the permanent vocabulary.
  They are ephemeral command surfaces scoped to the current mission overlay.
- Telemetry now has two separate concepts:
  - `match`: VoiceAttack's exact-name `Command.Exists` result for static commands only.
  - `resolution` / `dispatch`: VAIVOX's typed surface resolution and adapter result.
- The command browser may show human labels, but the F10 source must preserve VAICOM's
  identifier and metadata for routing.
- ADR-0011 remains useful as the conservative scoring policy, but "snap to phrase" is no
  longer the main routing model. For typed routing, the result is "resolve to command
  surface".

## Action Items

1. [x] Add pure domain command-surface value objects and `CommandSurfaceResolver`.
2. [x] Add the typed `CommandDispatcher` port and keep the existing VoiceAttack sink as
   the `VoiceAttackCommand` adapter.
3. [x] Parse mission F10 log entries into `VaicomF10Action` surfaces while continuing to
   expose bare labels to the UI.
4. [x] Route through surface resolution first, then fallback to legacy VoiceAttack snap.
5. [x] Extend telemetry with `resolution` and `dispatch` without changing `match`
   semantics.
6. [ ] Validate real VAICOM/DCS F10 execution by smoke test, then replace the disabled
   `VaicomF10Action` sink with the active adapter behind an explicit setting/default.
