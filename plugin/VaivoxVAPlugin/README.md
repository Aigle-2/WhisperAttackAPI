# VAIVOX VoiceAttack plugin

The C# VoiceAttack plugin that bridges VoiceAttack ⇄ the VAIVOX Python server. It
sends `start` / `stop` / `shutdown` to the server's control socket and runs a small
listener that executes the command text VAIVOX sends back.

Since ADR-0006 (the **return channel**), the listener also **replies** on the same
connection with the match outcome — a one-line, `\n`-terminated UTF-8 JSON object
`{"v":1,"matched":true,"resolved_command":"…"}` (`resolved_command` is `null` when
not matched). VAIVOX reads that reply to drive live metrics and the vocabulary
learning loop. The reply is **best-effort**: an old app that does not read it just
makes the plugin's write hit a broken pipe, which is caught and ignored (the
compatibility matrix in [`docs/RETURN_CHANNEL_PLAN.md`](../../docs/RETURN_CHANNEL_PLAN.md)).

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

VoiceAttack loads a compiled **.NET Framework 4.8** DLL. The project file
`VaivoxVAPlugin.csproj` is now committed and builds **without any `VoiceAttack.dll`
reference**: the plugin talks to VoiceAttack only through `dynamic vaProxy`, so it
needs no compile-time reference to the host. The net48 reference assemblies come from
the [`Microsoft.NETFramework.ReferenceAssemblies`](https://www.nuget.org/packages/Microsoft.NETFramework.ReferenceAssemblies)
NuGet package, so `dotnet build` works cross-platform (Linux/macOS/Windows CI) with
**no .NET Framework targeting pack and no VoiceAttack installed**.

```bash
# from the repo root
dotnet build  plugin/VaivoxVAPlugin.sln --configuration Release   # builds plugin + tests
dotnet test   plugin/VaivoxVAPlugin.sln --configuration Release   # xUnit vs golden vectors
```

Build output (the DLL VoiceAttack loads):

```
plugin/VaivoxVAPlugin/bin/Release/net48/VaivoxVAPlugin.dll
```

Drop that `VaivoxVAPlugin.dll` into `VoiceAttack\Apps\VAIVOX\`.

### Bundled in the release (M6)

You normally do **not** build the plugin by hand: `build_exe.ps1` bundles it. It calls
`build_plugin.ps1` (`dotnet build plugin/VaivoxVAPlugin.sln -c Release`) and copies the DLL
**and** the `VAIVOX - VA Profile.vap` into the release under **`Apps\VAIVOX\`**, mirroring
the install target `<VoiceAttack>\Apps\VAIVOX\`:

```
<release>\Apps\VAIVOX\VaivoxVAPlugin.dll
<release>\Apps\VAIVOX\VAIVOX - VA Profile.vap
```

So deploying is just copying that `Apps\VAIVOX\` subtree onto the VoiceAttack install.

- The plugin needs **no VoiceAttack reference**, so any machine with the **.NET SDK** can
  build it. The **official release must be built on a machine with the SDK** so the plugin
  ships.
- If the SDK is absent, `build_exe.ps1` **fails hard** with a clear message by default
  (it will not silently publish a release without the return channel). Pass
  `build_exe.ps1 -SkipPlugin` to deliberately package an **app-only** build (no plugin).

### Version stamp (M6)

The plugin carries an explicit assembly version (`<Version>` / `<AssemblyVersion>` /
`<FileVersion>` in `VaivoxVAPlugin.csproj`) and a protocol-version constant
`VA_Plugin.MatchProtocolVersion`, which **must equal** Python's
`MATCH_PROTOCOL_VERSION` (`protocol.py`, currently `1`) — the shared golden vectors
(`tests/contract/match_protocol_vectors.json`) assert the two serializations agree.

Both sides **log their version at startup** so a mismatch is visible:

- **Plugin** — `VA_Init1` writes `VAIVOX plugin <assembly-version>, match protocol v1` to
  the VoiceAttack log.
- **App (Python)** — the composition root logs `Return channel: match protocol v1,
  await_result=<bool>` to `%LOCALAPPDATA%\VAIVOX\VAIVOX.log`, and `GET /status` exposes
  `protocol_version`.

Bump `<Version>` when you ship a new DLL; the protocol version only changes if the wire
format changes (frozen at `1` for ADR-0006).

## Deployment & rollback (return channel, ADR-0006)

The return channel is rolled out in **two decoupled stages** so a mixed app/plugin pair is
always safe (compatibility matrix in
[`docs/RETURN_CHANNEL_PLAN.md`](../../docs/RETURN_CHANNEL_PLAN.md)):

1. **Ship the Python app first.** It is harmless against the old (non-replying) plugin: the
   sink times out and records `unknown`, never blocking. Keep `voiceattack_await_result`
   **off** at this point (the default).
2. **Deploy the plugin.** Copy `Apps\VAIVOX\VaivoxVAPlugin.dll` (and re-point the `.vap`,
   one-time, because the GUID changed) and **restart VoiceAttack**.
3. **Flip the kill-switch on.** Set `voiceattack_await_result = true` in
   `%LOCALAPPDATA%\VAIVOX\settings.cfg` and restart VAIVOX — now the sink reads the real
   match outcome and `/metrics` populates.

**Rollback** (if the new plugin misbehaves): restore the **previous** `VaivoxVAPlugin.dll`
(keep the prior DLL from the last release for exactly this), set
`voiceattack_await_result = false` (instant kill-switch — fire-and-forget even with a bad
plugin installed), and **restart VoiceAttack + VAIVOX**. No data loss; telemetry and
vocabulary are untouched. The full step-by-step is the
[E2E runbook](../../docs/RETURN_CHANNEL_E2E_RUNBOOK.md) §6.

### Tests (ADR-0006, AC4)

`plugin/VaivoxVAPlugin.Tests/` (xUnit, net48) asserts the plugin's pure return-channel
logic with **no VoiceAttack and no socket**:

- `BuildReply(matched, resolvedCommand)` is verified **byte-for-byte** against the
  shared golden vectors [`tests/contract/match_protocol_vectors.json`](../../tests/contract/match_protocol_vectors.json)
  — the same file the Python serializer (`protocol.py::build_reply`) is tested against,
  so the two implementations can never drift (compact JSON, stable key order
  `v`/`matched`/`resolved_command`, raw UTF-8, single `\n`).
- `Decide(probe, text)` is exercised with a fake `ICommandProbe` (matched/not-found,
  and that `Execute` runs only when the command exists).

A `dotnet` job on `windows-latest` runs `dotnet build` + `dotnet test` in CI
(`.github/workflows/ci.yml`); the full VoiceAttack end-to-end stays a manual
pre-release step.

## VoiceAttack setup

1. Import `VAIVOX - VA Profile.vap` (the bundled profile template).
2. Because the plugin GUID changed, **re-point** each command's *Execute an external
   plugin function* to the **VAIVOX** plugin (expected one-time step; ADR-0002).
3. Bind your push-to-talk buttons to the two commands the plugin matches on:
   - `Start Whisper Recording` → sends `start`
   - `Stop Whisper Recording` → sends `stop`
   (The command *names* are kept so the bundled profile keeps working; only the plugin
   reference needs re-pointing.)
