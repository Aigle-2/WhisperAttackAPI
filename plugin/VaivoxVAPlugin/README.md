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

VAIVOX supports side-by-side installation with upstream WhisperAttack by keeping a
separate plugin GUID, display name, app folder, profile name, and `%LOCALAPPDATA%\VAIVOX`
data directory. Running both STT servers at the same time is not supported yet because
the default localhost ports are still shared.

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

The project file (`VaivoxVAPlugin.csproj`) targets **.NET 8.0**, matching the VoiceAttack 2
plugin samples and help docs. The assembly name is pinned to `VaivoxVAPlugin.dll`
(VoiceAttack loads by file name). The plugin uses only the late-bound `dynamic vaProxy`
API, so it builds without referencing `VoiceAttack.dll`.

```powershell
dotnet build plugin\VaivoxVAPlugin\VaivoxVAPlugin.csproj -c Release
```

Release users can run `Install VAIVOX VoiceAttack Plugin.exe` from the extracted VAIVOX
release folder. It copies the bundled DLL into `%APPDATA%\VoiceAttack2\Apps\VAIVOX\`,
the VoiceAttack 2.1.8+ preferred third-party plugin folder, and also updates the detected
VoiceAttack install's `<VoiceAttack>\Apps\VAIVOX\` folder when available.

For manual development installs, copy
`plugin\VaivoxVAPlugin\bin\Release\net8.0\VaivoxVAPlugin.dll` into
`%APPDATA%\VoiceAttack2\Apps\VAIVOX\` (create the folder). Restart VoiceAttack to load it.

## VoiceAttack setup

1. Import `VAIVOX - VA Profile.vap` (the bundled profile template).
2. Because the plugin GUID changed, **re-point** each command's *Execute an external
   plugin function* to the **VAIVOX** plugin (expected one-time step; ADR-0002). The `.vap`
   is a binary/encrypted VoiceAttack export — there is no plaintext GUID to swap, so this
   **must be done in the VoiceAttack GUI**, not by editing the file.
3. Bind your push-to-talk buttons to the two commands the plugin matches on:
   - `Start VAIVOX Recording` -> sends `start`
   - `Stop VAIVOX Recording` -> sends `stop`

The plugin intentionally matches only VAIVOX-named contexts, so an upstream
WhisperAttack profile can remain installed without sharing action names with VAIVOX.

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
