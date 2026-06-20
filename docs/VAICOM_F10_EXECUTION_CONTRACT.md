# VAICOM F10 execution contract (reverse-engineered)

How a DCS **F10 radio-menu action** actually fires, and how VAIVOX reproduces it without
VAICOM's voice recognition. Reverse-engineered from
[VAICOM-Community](https://github.com/Penecruz/VAICOM-Community) source and **confirmed
live** (2026-06-20) against the operator's install. This is the reference behind
[ADR-0012](adr/0012-command-surfaces-and-typed-dispatch.md).

## TL;DR

To fire an F10 item, send one UDP datagram to DCS and it runs `doAction`:

```
UDP 127.0.0.1:33491  →  {"type":"mission.player.actionsequence","actionsequence":[<ActionIndex>]}
                     →  DCS: missionCommands.doAction(<ActionIndex>)
```

- `<ActionIndex>` is the **small** index from the log line
  `Set menu F10 item: Action FLEX NORTH, ActionIndex: 0, Command ID: 20086` → send `0`.
- It is **not** the `Command ID` (`20086`); that is VAICOM's internal id and does nothing.
- A **single** `ActionIndex` fires any item, including nested submenu items. It is not a
  navigation path.

## Why F10 items are not VoiceAttack commands

VAICOM imports the DCS F10 menu into its own database; it does **not** create VoiceAttack
commands for the items. Verified by grepping every active profile —
`VAICOM F-4E WSO.vap`, `VAICOM PRO for DCS World.vap`, `VAIVOX - VA Profile.vap` — for
`Action …`: **zero matches**. Consequently, dispatching `Action FLEX NORTH` (or the bare
`FLEX NORTH`) through the VoiceAttack command socket always returns `matched=false` from the
plugin return channel (ADR-0006), and nothing fires. F10 must take the UDP `doAction` path.

## How VAICOM builds and sends the action (client side, C#)

When a recognized command resolves to an imported F10 item, message construction switches to
the action-sequence type and appends the item's `actionIndex`:

- `VAICOM/Client/Message construction/ConstructMessage.cs` (≈ lines 1109–1114):
  ```csharp
  // For imported F10 menu commands: change type and add action sequence..
  if ((State.currentrecipientclass.Equals(Recipientclasses.Aux) && ...) & !State.currentcommand.isOptions())
  {
      State.currentmessage.type = Messagetypes.ActionIndexSequence;
      Message.SetMenuItemAction();
  }
  ```
- `VAICOM/Client/Message construction/SetMenuItemAction.cs`:
  ```csharp
  State.currentmessage.actionsequence.Add(State.currentcommand.actionIndex); // ONE index
  ```
- `VAICOM/Settings/Static.cs`: `ActionIndexSequence = "mission.player.actionsequence"`.

So the wire message is `{"type":"mission.player.actionsequence","actionsequence":[idx]}`.
The actionsequence is a `List<int>` (`MessageTypes.cs`); for a single command it holds one
element.

### Where the menu items + indices come from

`VAICOM/Server/AuxMenu.cs` imports the live F10 tree DCS sends (`State.currentstate.menuaux`):

- `ImportAuxMenu()` logs `Mission title: <title>, Menu name: <menu>` then `ScanTree()`.
- `ScanTree()` walks the tree (iterative DFS). For each item it forms
  `identifier = "Action " + name`, logs `Adding new menu item: <identifier>` (or
  `Updating existing menu item: <identifier>` if already known), and stores
  `actionIndex = menuItem.command.actionIndex`.
- `SetImportedMenusAsCommands()` assigns a sequential `Command ID` (from 20000) and logs
  `Set menu F10 item: <identifier>, ActionIndex: <n>, Command ID: <id>` — **only on first
  registration** of a command.

This is why later sessions show index-less `Adding/Updating` lines: the `ActionIndex` is in
the older `Set …` line.

## How DCS consumes it (server side, Lua)

VAICOM appends a handler to the DCS radio panel:

- `VAICOM/Resources/Files/Append.Core.RadioCommandDialogsPanel.lua` (≈ 636–642):
  ```lua
  if clientmessage.type == base.vaicom.messagetype.actionsequence then
      for i = 1, #clientmessage.actionsequence do
          base.missionCommands.doAction(clientmessage.actionsequence[i])
      end
      socket.try(base.vaicom.sender:send(base.vaicom.flags.raw))
      return
  end
  ```
- `doAction` is the *same* call the manual click handler uses
  (`Orig.Core.RadioCommandDialogsPanel.lua:177`, `DoMissionAction.perform`). DCS resolves a
  registered mission action by its handle, so one index fires nested items directly.
- The handler reads only `type` + `actionsequence`; all other fields are optional, so the
  minimal datagram above is sufficient.

## Transport / ports

- `VAICOM/Interfaces/UDP.cs:41` and `Settings/Config.cs:350`: `ClientSendPort = 33491` —
  VAICOM's client sends actions here. Replies come back on `33492`.
- `Append.…lua` (≈ 975–985): the in-sim panel receiver binds `33334`;
  `VAICOMPRO.export.lua` relays inbound `:33491` → `:33334`. So **send to `33491`** to match
  VAICOM exactly (confirmed delivered + processed).

## ActionIndex vs Command ID (the root-cause bug)

| Field | Example (FLEX NORTH) | Meaning | Use for doAction? |
|-------|----------------------|---------|-------------------|
| `ActionIndex` | `0` | DCS action handle for the current menu | ✅ **yes** |
| `Command ID` | `20086` | VAICOM's internal sequential id (≥ 20000) | ❌ no |

An earlier probe sent `[20086]` and saw no effect, which led to a mistaken "needs a
navigation path" conclusion. The real fix is to send the `ActionIndex` (`0`).

## Sourcing the live ActionIndex in VAIVOX

- The current mission block has labels but no index. VAIVOX still reads historical
  `Set menu F10 item` values as diagnostic metadata, but they are never eligible for
  dispatch (`mission_f10.py::_action_metadata_map`).
- **This is not reliable, and the operator's real log proves it.** VAICOM logs the index
  only on a command's *first* registration; later scans log index-less `Adding/Updating`
  lines while updating the index **in memory** (`AuxMenu.cs`). The log value is therefore
  frozen and drifts from the live menu. On the real log (2026-06-20): the current mission
  block had **0** fresh `Set` lines, and **8** `ActionIndex` values mapped to two commands
  across the log — `0` = `FLEX NORTH` *or* `Repeat last transmission`, `1` = `FLEX WEST` *or*
  `Squawk 2001`, `2` = `FLEX MMM TRANSITION` *or* `Squawk 1001`, etc. A stale index fires the
  **wrong** action.
- **The reliable source is the live DCS menu**, the same data VAICOM reads as
  `State.currentstate.menuaux`. VAICOM only emits it to its own bound port `33492`, and the
  menu exists only in the panel environment, so there is no pure VAIVOX-side way to read it
  — a DCS-side hook is unavoidable. VAIVOX therefore ships its **own** hook (it does not
  touch VAICOM): `DcsHookInstaller` self-heals a marker-guarded Lua block into the radio
  command panel that scans the authoritative `data.menuOther` tree (the exact object VAICOM
  assigns to `base.vaicom.state.menuaux`) on a throttled GUI update callback. It extracts
  each command's label, submenu path, and `command.actionIndex`, then broadcasts protocol-v2
  cumulative snapshots to a VAIVOX-owned UDP port (default `33493`). Each snapshot carries a
  process session id and revision. `MissionMenuListener` debounces the build, rejects stale
  revisions and duplicate
  labels on distinct paths, and supplies the only dispatchable index. Every mutation
  immediately invalidates the previous map, and the UDP sink resolves the label from the
  settled map again at send time. The hook is re-applied on every VAIVOX startup so it
  survives DCS/VAICOM updates with no manual step.
- Live testing exposed two DCS-specific integration facts. In v4, after `module(...)`, bare
  `pcall` and `type` are nil; v5 fixed that with `base.pcall` / `base.type` and validated the
  complete UDP handshake. But v5's late replacements of `clearOtherMenu` and
  `addOtherCommand` stayed at revision 1 while VAICOM was actively importing the menu: DCS
  had retained the original callbacks. Upstream VAICOM confirms that its real source is the
  lexical `data.menuOther` tree, so v6 scans that object directly after
  `base.vaicom.init.start` registers the GUI update machinery. The listener starts empty
  every time and never restores persisted action handles. **Status: v6 live capture
  validated on 2026-06-20:** DCS published revision 3 with 88 commands and complete submenu
  paths; VAIVOX received the same session with no ambiguous labels. Until a current scan
  arrives, F10 items remain visible but non-dispatchable. A spoken-command dispatch smoke is
  the only remaining end-to-end check.

## Live validation (2026-06-20)

Sending `{"type":"mission.player.actionsequence","actionsequence":[0]}` to
`127.0.0.1:33491` while in the AI ATC Nellis mission fired **FLEX NORTH**. Confirms the
transport, message shape, and single-index-fires-nested-item behaviour.

**Caveat from the same session:** minutes later, after the live menu changed, index `0`
resolved to `Repeat last transmission` — the transport still worked, but the *index* was
stale (see the sourcing limitation above). The transport and v6 live-index capture are now
proven; the remaining smoke is the complete spoken-command route into that current index.

## VAIVOX implementation

- Port: `application/ports.py::VaicomF10ActionSink`.
- Adapter: `infrastructure/voiceattack/vaicom_f10_sink.py::UdpVaicomF10ActionSink`.
- Routing: `infrastructure/voiceattack/dispatcher.py::TypedCommandDispatcher` →
  `VaicomF10Action` to the F10 sink; `VoiceAttackCommand` to the command sink.
- Index sourcing: `infrastructure/vocabulary/mission_f10.py` (current live map only;
  historical log values are diagnostic and fail closed).
- Live menu hook: `infrastructure/dcs/hook_installer.py::DcsHookInstaller` (self-heal) +
  `infrastructure/dcs/menu_listener.py::MissionMenuListener` (UDP capture on `33493`).
- Config (`settings.py`): `vaicom_f10_host`/`vaicom_f10_port` (dispatch, default
  `127.0.0.1:33491`); `vaicom_f10_menu_port` (listener, default `33493`);
  `vaicom_f10_live_menu` (enable, default on); `dcs_install_dir` (override only — the base
  install is auto-discovered via the ED registry and the Steam library that owns app id
  `223750`, so multiple/relocated DCS installs resolve to the active one).

## References

- VAICOM-Community: <https://github.com/Penecruz/VAICOM-Community>
- AI ATC Nellis mission: <https://github.com/Avalanche110/AI_ATC_Nellis_AFB>
- [ADR-0012](adr/0012-command-surfaces-and-typed-dispatch.md),
  [ADR-0006](adr/0006-telemetry-via-plugin-return-channel.md)
