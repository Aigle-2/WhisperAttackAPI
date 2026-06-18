# VAIVOX VoiceAttack plugin

The C# VoiceAttack plugin that bridges VoiceAttack ⇄ the VAIVOX Python server. It
sends `start` / `stop` / `shutdown` to the server's control socket and runs a small
listener that executes the command text VAIVOX sends back, replying with the match
outcome so the server can close the reconciliation loop (ADR-0006).

## Identity (ADR-0002)

| Field | Value |
|-------|-------|
| Plugin GUID | `{ED0BA443-726F-4A9F-AF05-DB400F39A501}` (distinct from upstream) |
| Display name | `VAIVOX` |
| Control port (plugin → server) | `65432` |
| Listener port (server → plugin) | `65433` |

These ports mirror `vaivox.infrastructure.config.identity.ProductIdentity`. The GUID is
fresh so VoiceAttack treats VAIVOX as a separate plugin from any upstream WhisperAttack
install.

## Return channel (ADR-0006)

After receiving a command on the listener port, the plugin runs
`vaProxy.Command.Exists(...)` and writes **one JSON line back on the same socket** before
executing the command:

```json
{"text": "<received>", "matched": true, "resolved_command": "<command or null>"}
```

`resolved_command` is the received text when matched (VoiceAttack's `Command.Exists` is an
exact-name check), otherwise `null`. The reply is sent **before** `Command.Execute`, so it
does not wait on the in-game radio call. It is best-effort: the server applies a short read
timeout and treats a missing/garbled reply as *unknown*, so an older server build (or none)
never breaks dispatch. The Python side reads it in
`vaivox.infrastructure.voiceattack.sink.VoiceAttackCommandSink.send`.

## Building

The project file (`VaivoxVAPlugin.csproj`) targets **.NET Framework 4.8** (the runtime
VoiceAttack 2 loads) and pins the assembly name to `VaivoxVAPlugin.dll` (VoiceAttack loads
by file name). The plugin uses only the late-bound `dynamic vaProxy` API, so it builds
**with or without** a local VoiceAttack install — `VoiceAttack.dll` is referenced when
present and skipped otherwise (the build also stays reproducible in CI via the
`Microsoft.NETFramework.ReferenceAssemblies` build-time package).

```powershell
dotnet build plugin\VaivoxVAPlugin\VaivoxVAPlugin.csproj -c Release
# VoiceAttack installed somewhere non-default? point the build at it:
dotnet build plugin\VaivoxVAPlugin\VaivoxVAPlugin.csproj -c Release -p:VoiceAttackDir="D:\Games\VoiceAttack"
```

Then copy `plugin\VaivoxVAPlugin\bin\Release\net48\VaivoxVAPlugin.dll` into
`VoiceAttack\Apps\VAIVOX\`.

## VoiceAttack setup

1. Import `VAIVOX - VA Profile.vap` (the bundled profile template).
2. Because the plugin GUID changed, **re-point** each command's *Execute an external
   plugin function* to the **VAIVOX** plugin (expected one-time step; ADR-0002).
3. Bind your push-to-talk buttons to the two commands the plugin matches on:
   - `Start Whisper Recording` → sends `start`
   - `Stop Whisper Recording` → sends `stop`
   (The command *names* are kept so the bundled profile keeps working; only the plugin
   reference needs re-pointing.)

## End-to-end smoke (manual, needs VoiceAttack + VAICOM + DCS)

With the server, VoiceAttack, VAICOM, and DCS running (enable the introspection API with
`api_enabled = true` in the per-user `settings.cfg` — see
[`.claude/skills/vaivox-debug/SKILL.md`](../../.claude/skills/vaivox-debug/SKILL.md)):

1. **Known command** → PTT a command that exists. It fires in-game; the VAIVOX log /
   telemetry shows `matched=true resolved_command=...`; `GET /metrics` shows a real `match`;
   `GET /reconciliations` shows the outcome; and the credited entry gains a hit in
   `%LOCALAPPDATA%\VAIVOX\<kind>.usage.json`.
2. **Unknown command** → PTT something with no matching command. The reply is
   `matched=false`, the snapper's near-miss is recorded in telemetry, and no usage is
   stamped.
