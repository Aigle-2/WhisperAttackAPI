# ADR-0012: Command surfaces and typed dispatch

**Status:** Accepted (amended 2026-06-20)
**Date:** 2026-06-19
**Deciders:** Project owner (Aigle_2)

> **Amendment 2026-06-20 (supersedes the 2026-06-19 amendment).** The prior amendment
> assumed VAICOM exposes mission F10 items as VoiceAttack commands (`Action FLEX NORTH`)
> and routed F10 dispatch through the VoiceAttack command port. That premise was **wrong**:
> a grep of every active profile (`VAICOM F-4E WSO.vap`, `VAICOM PRO for DCS World.vap`,
> `VAIVOX - VA Profile.vap`) finds **zero** `Action …` commands, and the plugin return
> channel reports `matched=false` for them. VAICOM fires F10 items over a **UDP
> `doAction`** path instead. This amendment corrects the decision to replicate that path;
> the corrected approach is **confirmed working live**. Full source-level write-up:
> [`docs/VAICOM_F10_EXECUTION_CONTRACT.md`](../VAICOM_F10_EXECUTION_CONTRACT.md).

## Context

VAIVOX originally treated reconciled text as the executable VoiceAttack command:
`reconcile(...) -> PhraseSnapper -> Command.Exists/Execute(text)`. Static commands do use
their command name, but mission F10 items imported by VAICOM are different in kind:

- they have a human menu label such as `FLEX NORTH`;
- VAICOM tracks them internally under the identifier `Action FLEX NORTH`, with an
  `ActionIndex` and a `Command ID` logged in `VAICOMPRO.log`;
- **they are not VoiceAttack commands.** VAICOM does not register an `Action …` command in
  any VoiceAttack profile, so `Command.Exists("Action FLEX NORTH")` is always false.

Reading VAICOM-Community source settles how F10 actually fires (see the contract doc for
file/line citations):

- `ConstructMessage.cs` → `SetMenuItemAction.cs` appends the item's `actionIndex` to an
  `actionsequence` list and sends `{"type":"mission.player.actionsequence",
  "actionsequence":[<actionIndex>]}` to VAICOM's client send port `127.0.0.1:33491`.
- DCS (`Append.Core.RadioCommandDialogsPanel.lua`) loops the array and calls
  `missionCommands.doAction(actionsequence[i])`.
- `doAction(actionIndex)` is the same call DCS makes when you click the menu item by hand.
  It fires a registered mission action **by its handle**, so a *single* `actionIndex` fires
  any item — submenu nesting is irrelevant; it is **not** a navigation path.

`Command ID` (VAICOM's sequential id, 20000-range) is a diagnostic only — it is *not* the
DCS action index. `ActionIndex` is the executable value.

## Decision

Model recognized commands as **command surfaces** with typed dispatch targets, and
dispatch each target through the transport that actually executes it.

- `CommandSurface` carries a human label, aliases, source, scope, and a typed target.
- `VoiceAttackCommand(command_name)` targets a static VoiceAttack command. It dispatches
  through `CommandSink` (exact-name `Command.Exists`/`Execute` + the return channel,
  ADR-0006).
- `VaicomF10Action(identifier, label, command_id, action_index)` targets a live imported
  action. It dispatches through a **separate** `VaicomF10ActionSink`, not VoiceAttack.
  `action_index` is the executable value; `identifier`/`label` are for display and
  telemetry; `command_id` is diagnostic only.
- `UdpVaicomF10ActionSink` replicates VAICOM's datagram exactly: it sends
  `{"type":"mission.player.actionsequence","actionsequence":[action_index]}` over UDP to
  `127.0.0.1:33491` (overridable via `vaicom_f10_host` / `vaicom_f10_port`). This is
  **fire-and-forget** — DCS sends no acknowledgement — so F10 dispatch yields a
  `DispatchOutcome` only, never a `MatchOutcome`.
- `CommandSurfaceResolver` resolves whole-query exact matches first. It then recognizes the
  exact anchored grammar `Set call sign|callsign <label>` for a unique live F10 callsign
  label, tolerating the common STT inflection `Sets callsign`, and including AI_ATC's
  numeric `Set Integer` leaves. A full DCS callsign number such as `Set call sign 13`
  resolves to the leading `1` leaf because that is the only executable menu action AI_ATC
  exposes. This safely permits `Set call sign Chaos` without making every incidental
  single-token callsign eligible. Before fuzzy scoring, it may also resolve a live F10
  **label** embedded as a contiguous token sequence in a longer radio call. Only labels of
  at least two normalized tokens participate; the unique most-specific match wins (most
  tokens, then longest normalized label), and equal specificity abstains. Thus `DREAM 7`
  beats the numeric `7` inside a full clearance call, while bare `7` remains available as an
  exact whole command. Trusted semantic aliases from the mission vocabulary adapter can
  participate in embedded matching (for example `request taxi for takeoff` for the live
  `Request Taxi to Runway` label). Diagnostic aliases are not considered in either special
  phase.
  Fuzzy mission F10, fuzzy static, and raw fallback keep the existing conservative snap
  thresholds.
- **ActionIndex sourcing.** The authoritative source is the live DCS menu, delivered by a
  VAIVOX-owned hook (below). `mission_f10.py` clears every log-derived index before applying
  the current live map. The unreliable value from `Set menu F10 item: …, ActionIndex: N`
  remains diagnostic metadata only: a missing handshake, missing label, listener fault, or
  ambiguous label leaves the item visible but non-dispatchable. The UDP sink resolves the
  label from that map again at send time, so a surface created before a menu rebuild cannot
  carry an old handle into dispatch.
- **Live menu hook.** A small Lua block, self-healed into the DCS radio command panel by
  `DcsHookInstaller` (idempotent, marker-guarded, re-applied on every VAIVOX startup so it
  survives DCS/VAICOM updates), scans the panel's authoritative `data.menuOther` tree on a
  throttled GUI update callback. This is the same tree VAICOM assigns to
  `base.vaicom.state.menuaux`; late replacement of `clearOtherMenu` / `addOtherCommand` was
  rejected after live v5 testing showed DCS kept cached references and bypassed the wrappers.
  The scanner broadcasts a protocol-v2 cumulative snapshot over UDP to a VAIVOX-owned port
  (default `33493`). Each snapshot has a DCS-process session id and monotonic menu revision.
  It also re-sends the settled snapshot every five seconds **at the same revision**. This
  heartbeat lets a VAIVOX process restarted after DCS establish a new live handshake; an
  already-synchronized listener rejects the duplicate revision without invalidating its
  handles. `MissionMenuListener` debounces changed snapshots, rejects stale revisions and
  ambiguous duplicate labels, and persists a diagnostic mirror that is never restored for
  dispatch. This is fully VAIVOX-owned: it never touches VAICOM or contends for a
  VAICOM-bound socket.
- When no surface resolves, VAIVOX keeps the legacy fallback: phrase-snap and dispatch the
  resulting text as a static `VoiceAttackCommand`.

## Consequences

- F10 mission commands fire through VAIVOX without VAICOM voice recognition, by the same
  mechanism VAICOM itself uses. A single `actionIndex` reaches nested items.
- A small VAICOM transport setting **is** needed (`vaicom_f10_host`/`vaicom_f10_port`,
  default `127.0.0.1:33491`); no VAICOM/DCS installation patch is required — the existing
  `VAICOMPRO.export.lua` relay forwards `:33491` to the in-sim panel.
- Telemetry keeps two concepts: `match` is VoiceAttack's exact-name acceptance, recorded
  for **static** targets only; F10 dispatch records `resolution` + `dispatch` (with
  `target_kind = vaicom_f10_action`) and no `match`, since the UDP path has no reply.
- The command browser shows bare human labels while dispatch carries the `ActionIndex`.
- **The log-derived index is unreliable and is never dispatched.** VAICOM logs
  `Set menu F10 item: …, ActionIndex: N` only on a command's
  *first* registration; later menu scans log index-less `Adding/Updating` lines while
  updating the index **in memory** (`AuxMenu.cs`). So the log value is frozen at
  first-seen and drifts as the live menu changes. Confirmed on the operator's real log
  (2026-06-20): the current mission block had **0** fresh `Set` lines, and **8**
  `ActionIndex` values mapped to two different commands across the log — e.g. `0` =
  `FLEX NORTH` *or* `Repeat last transmission`, `1` = `FLEX WEST` *or* `Squawk 2001`. After
  the live menu changed, index `0` resolved to `Repeat last transmission` even though it had
  fired `FLEX NORTH` minutes earlier. A stale index therefore fires the **wrong** action.
  This is what the live menu hook (above) resolves by capturing the *current* index. Until
  the hook is validated live, F10 dispatch fails closed rather than using the log value.

## Rejected approach: F10 via a VoiceAttack `Action …` alias

The 2026-06-19 amendment routed F10 targets through the VoiceAttack command port, sending
`Action FLEX NORTH` and expecting VAICOM to resolve it. Rejected: VAICOM registers no such
VoiceAttack command (zero `Action …` entries in any profile), so the plugin always replies
`matched=false` and nothing fires. The added "explicit-negative-only legacy fallback" then
sent the bare label, which also is not a VoiceAttack command — so it could only ever fire
by coincidence (a same-named static command). This path is removed.

## Rejected approach: replaying the Command ID

An earlier experimental probe sent `actionsequence:[<Command ID>]` (e.g. `20086`). Rejected:
`Command ID` is VAICOM's internal id, not a DCS action index, so `doAction` did nothing.
The correct value is the small `ActionIndex` from the same log line (e.g. `0`). This was the
root cause of the earlier (mistaken) "single id cannot fire nested items" conclusion.

## Validation status

**Transport confirmed working live (2026-06-20).** Sending
`{"type":"mission.player.actionsequence","actionsequence":[0]}` to `127.0.0.1:33491` while
in the AI ATC Nellis mission fired `FLEX NORTH` (its logged `ActionIndex` was `0`). This
proves the transport, the message shape, and the single-index-fires-nested-item property.

**Index sourcing is fail-closed and v6 live capture is validated.** A follow-up check minutes later
showed index `0` now resolved to `Repeat last transmission`, and the whole-log scan found
8 ambiguous indices with 0 fresh `Set` lines in the current block. Historical values are
therefore no longer eligible for dispatch. Live v5 testing fixed and validated the DCS
namespace/transport path (`base.pcall` / `base.type`, protocol-v2 handshake), but showed the
late function wrappers never observed mission menu changes. Upstream VAICOM confirms its
authoritative source is `data.menuOther`, so v6 scans that tree directly. Live validation on
2026-06-20 captured 88 commands at revision 3 with full submenu paths and no ambiguous
labels; the VAIVOX listener persisted the same DCS session and indices (`FLEX NORTH=0`,
`MORMON MESA 8=5`). The listener accepts only current protocol-v2 session snapshots. The
The spoken software route was then validated with real ElevenLabs output
`Voice command assist`: exact mission-surface resolution, send-time live lookup, and
`actionsequence:[6]` dispatch all succeeded and were recorded in telemetry. Because the DCS
transport has no acknowledgement, the final mission effect remains operator-observed.

**Full AI ATC phrase resolution is regression-covered.** Two real operator transcripts,
`Clearance Lion 6-1 Clearance on request IFR DREAM 7` and `Clearance delivery Lion 61
Clearance on request IFR DREAM 7`, now resolve uniquely to the typed `DREAM 7` F10 surface
against a live-like menu containing other departure routes, callsigns, and numeric `0–9`
entries. The numeric entries no longer hijack the call; genuine equal-specificity matches
still abstain.

**VAIVOX-after-DCS restart race fixed in v7.** Live operator evidence exposed the gap: DCS
had published revision 3 at 04:14, then VAIVOX restarted at 04:38. The new listener correctly
refused to restore the 04:14 disk mirror, but v6 only transmitted when the menu changed, so
the listener could remain empty indefinitely (`DREAM 7` resolved correctly but could not
obtain its live index 3). v7 emits a same-revision heartbeat every five seconds. A restarted
listener accepts that live UDP snapshot, while an active listener ignores it without a
debounce gap, repeated notification, or handle invalidation.

**Anchored single-token callsign resolution is regression-covered.** Real operator output
`Set call sign Chaos` previously fell through to VoiceAttack because the generic embedded
phase correctly excludes single-token F10 labels. The explicit callsign grammar now resolves
that phrase to the typed `Chaos` surface. Numeric Set Integer leaves are accepted only via
the anchored callsign grammar (`Set callsign digit six`, `Set call sign 13` -> `1`), and
STT's `Sets callsign Chaos` inflection resolves the same way; unanchored mentions, trailing
composite name+digits (`Chaos 1-1`), and duplicate live labels remain fail-closed.

## Action Items

1. [x] Add pure command-surface value objects and `CommandSurfaceResolver`.
2. [x] Dispatch static commands via VoiceAttack and F10 actions via the UDP `doAction` sink.
3. [x] Preserve human F10 labels separately from VAICOM identifiers and the `ActionIndex`.
4. [x] Source the `ActionIndex` from the whole-log `Set menu F10 item` lines.
5. [x] Record typed resolution, dispatch, and (static-only) VoiceAttack match telemetry.
6. [x] Validate the UDP `doAction` contract live.
7. [x] Robust `ActionIndex` sourcing from the live DCS menu: a VAIVOX-owned panel hook
   (`DcsHookInstaller`, self-healing) broadcasts the current menu to `MissionMenuListener`,
   which supplies the only dispatchable index.
8. [x] Validate live hook installation and menu capture: v6 broadcast 88 current commands
   with paths/indices and VAIVOX received the identical session snapshot. The DCS install dir is
   auto-discovered (ED registry, then the Steam library owning app id 223750); the
   `dcs_install_dir` setting is only an override for non-standard installs.
9. [ ] Optional: recipient/segmentation handling for F10 items that need it.
10. [x] Fail closed without a current-session live index; never restore persisted action
    handles or dispatch historical log values.
11. [x] Stamp snapshots with protocol/session/revision metadata and reject duplicate labels
    on distinct submenu paths.
12. [x] Re-resolve the live label at send time and invalidate the committed map immediately
    on every incoming menu mutation, closing the resolve-to-dispatch race.
13. [x] Replace bypassed v5 callback wrappers with a v6 scan of `data.menuOther`, matching
    VAICOM's own `menuaux` source and preserving submenu paths.
14. [x] Validate one spoken F10 command through reconciliation, send-time live-index lookup,
    and UDP actionsequence dispatch (`Voice command assist` -> current index 6).
15. [ ] Record operator confirmation of the resulting in-mission help/toggle effect; DCS
    provides no programmatic acknowledgement for `actionsequence`.
16. [x] Resolve unique, exact multi-token F10 labels embedded in realistic full radio calls,
    while requiring single-token menu entries to match the whole utterance.
17. [x] Re-publish the settled live menu at the same revision every five seconds, allowing a
    VAIVOX restart to reacquire the current DCS session without restoring persisted handles.
18. [x] Resolve exact anchored `Set call sign|callsign <label>` phrases to a unique live
    F10 callsign surface without reopening generic single-token embedded matching.
