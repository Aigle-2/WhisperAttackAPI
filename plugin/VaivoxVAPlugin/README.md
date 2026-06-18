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
VoiceAttack 2 loads — verified against VoiceAttack 2.1.8, runtime `v4.0.30319`) and pins the
assembly name to `VaivoxVAPlugin.dll` (VoiceAttack loads by file name). The plugin uses only
the late-bound `dynamic vaProxy` API, so it builds **with or without** a local VoiceAttack
install — `VoiceAttack.dll` is referenced when present and skipped otherwise (the build also
stays reproducible in CI via the `Microsoft.NETFramework.ReferenceAssemblies` build-time
package).

Point the build at your VoiceAttack install with `-p:VoiceAttackDir=...` or the
`VOICEATTACK_DIR` environment variable (Steam installs live under
`<library>\steamapps\common\VoiceAttack 2`):

```powershell
dotnet build plugin\VaivoxVAPlugin\VaivoxVAPlugin.csproj -c Release -p:VoiceAttackDir="E:\Jeux\steamapps\common\VoiceAttack 2"
# ...or set it once and just `dotnet build ... -c Release`:
setx VOICEATTACK_DIR "E:\Jeux\steamapps\common\VoiceAttack 2"
```

Then copy `plugin\VaivoxVAPlugin\bin\Release\net48\VaivoxVAPlugin.dll` into
`<VoiceAttack>\Apps\VAIVOX\` (create the folder; one DLL per app, mirroring the other
`Apps\*` plugins). Restart VoiceAttack to load it.

## VoiceAttack setup

1. Import `VAIVOX - VA Profile.vap` (the bundled profile template).
2. Because the plugin GUID changed, **re-point** each command's *Execute an external
   plugin function* to the **VAIVOX** plugin (expected one-time step; ADR-0002). The `.vap`
   is a binary/encrypted VoiceAttack export — there is no plaintext GUID to swap, so this
   **must be done in the VoiceAttack GUI**, not by editing the file.
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
