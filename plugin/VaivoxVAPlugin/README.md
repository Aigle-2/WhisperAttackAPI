# VAIVOX VoiceAttack plugin

The C# VoiceAttack plugin that bridges VoiceAttack ⇄ the VAIVOX Python server. It
sends `start` / `stop` / `shutdown` to the server's control socket and runs a small
listener that executes the command text VAIVOX sends back.

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

## Building

VoiceAttack loads a compiled DLL. Build `VaivoxVAPlugin.cs` against your VoiceAttack
install's `VoiceAttack.dll` reference (the `dynamic vaProxy` API) and drop the resulting
DLL into `VoiceAttack\Apps\VAIVOX\`. (A `dotnet` project file is intentionally not
committed yet — it depends on the local VoiceAttack SDK path.)

## VoiceAttack setup

1. Import `VAIVOX - VA Profile.vap` (the bundled profile template).
2. Because the plugin GUID changed, **re-point** each command's *Execute an external
   plugin function* to the **VAIVOX** plugin (expected one-time step; ADR-0002).
3. Bind your push-to-talk buttons to the two commands the plugin matches on:
   - `Start Whisper Recording` → sends `start`
   - `Stop Whisper Recording` → sends `stop`
   (The command *names* are kept so the bundled profile keeps working; only the plugin
   reference needs re-pointing.)
