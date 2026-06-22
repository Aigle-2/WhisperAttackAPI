# Return channel — manual end-to-end runbook (ADR-0006, M5 / AC5)

This is the **one** validation step that cannot run in CI: it needs a real **Windows +
VoiceAttack 2 + VAICOM Community + DCS** install and the **replying** C# plugin
(`VaivoxVAPlugin.dll`, M4). Everything below it in the plan — the wire protocol, the
learning loop, the adapter plumbing, the C# unit tests — is already proven on Linux/CI
(layers 0–4 in [`RETURN_CHANNEL_PLAN.md`](RETURN_CHANNEL_PLAN.md#test-strategy-by-layer)).
Here we confirm the **real** match signal flows back through the socket and lights up
`/metrics`, match-gated stamping, and the vocabulary learning loop.

Run this **by hand, pre-release**. It is the acceptance gate for **AC5**: *after deploy on
a real install, `/metrics` `unknown_rate` drops toward ~0 and `match_rate` /
`not_found_rate` become meaningful.*

> **Single-user note.** You control both sides, so you can skip canaries — rebuild, copy,
> restart. The compatibility matrix and the `voiceattack_await_result` kill-switch are
> still a cheap safety net (scenarios (c)/(d), and Rollback).

---

## Conventions used below

- The introspection API host/port come from `settings.cfg`
  (`api_host` / `api_port`, defaults `127.0.0.1:8765`). All `curl` / PowerShell examples
  below assume the defaults — substitute your overrides.
- If you set `api_token`, add `-H "Authorization: Bearer <token>"` to every API call
  (the PowerShell helper takes a `$Token` you can fill in).
- The control / listener ports are **65432** (plugin → server) and **65433**
  (server → plugin); the return-channel reply rides back on the **65433** connection.
- The per-user VAIVOX data directory is `%LOCALAPPDATA%\VAIVOX` — `settings.cfg`,
  `telemetry.jsonl`, the JSONL vocabulary sources, and the generated `phrase_index.txt`
  all live there.

A small PowerShell helper you can paste once and reuse for every check:

```powershell
$Api   = "http://127.0.0.1:8765"          # api_host:api_port from settings.cfg
$Token = ""                                # set if api_token is configured
$Hdr   = @{}; if ($Token) { $Hdr["Authorization"] = "Bearer $Token" }
function Vget  ($path)        { Invoke-RestMethod -Uri "$Api$path" -Headers $Hdr }
function Vpost ($path, $body) { Invoke-RestMethod -Uri "$Api$path" -Method Post -Headers $Hdr -ContentType 'application/json' -Body $body }
# usage:  Vget "/metrics" | ConvertTo-Json -Depth 6
#         Vpost "/reconcile/dry-run" '{"text":"two seven left"}'
```

---

## 1. Prerequisites

- [ ] **Get the plugin DLL + profile.** Since **M6** the release **bundles** both under
  `Apps\VAIVOX\` — if you built the release with `build_exe.ps1` (on a machine with the
  .NET SDK), they are already at `<release>\Apps\VAIVOX\VaivoxVAPlugin.dll` and
  `<release>\Apps\VAIVOX\VAIVOX - VA Profile.vap`; skip the manual build below.

  To build the plugin standalone (net48, no VoiceAttack reference needed — see
  [`plugin/VaivoxVAPlugin/README.md`](../plugin/VaivoxVAPlugin/README.md)):

  ```powershell
  # from the repo root
  dotnet build plugin/VaivoxVAPlugin.sln -c Release
  dotnet test  plugin/VaivoxVAPlugin.sln -c Release   # xUnit vs golden vectors should be green
  ```

  Expected artifact: `plugin/VaivoxVAPlugin/bin/Release/net48/VaivoxVAPlugin.dll`.
- [ ] **The profile** `VAIVOX - VA Profile.vap` (bundled in the release under
  `Apps\VAIVOX\`, or the repo-root template).
- [ ] A working **VoiceAttack 2** + **VAICOM Community** + **DCS** install, with VAICOM
  already configured and matching commands in your current DCS aircraft/theatre.
- [ ] **The VAIVOX app built** (PyInstaller via `build_exe.ps1`) **or** run from source
  (`uv run vaivox`, needs `--extra app` or `--extra full`).
- [ ] A push-to-talk key free to bind in VoiceAttack.
- [ ] (Recommended) `curl` available, or use the PowerShell helper above.

> Confirm the contract is frozen and consistent first (cheap, no Windows needed): the C#
> `dotnet test` above asserts `BuildReply` byte-for-byte against
> `tests/contract/match_protocol_vectors.json`, the same file the Python parser is tested
> against — so the two sides cannot have drifted.

---

## 2. Installation

### 2.1 Plugin + profile (VoiceAttack side)

- [ ] Copy the DLL into the VoiceAttack apps folder:
  `<VoiceAttack>\Apps\VAIVOX\VaivoxVAPlugin.dll`
  (create the `VAIVOX` folder if absent; one DLL per app folder). Since M6 the release ships
  this as `<release>\Apps\VAIVOX\VaivoxVAPlugin.dll`, so deploying is just copying that
  `Apps\VAIVOX\` subtree onto the VoiceAttack install.
- [ ] Confirm the version stamp: after restarting VoiceAttack, its log shows
  `VAIVOX plugin <version>, match protocol v1`; the VAIVOX log shows
  `Return channel: match protocol v1, await_result=...` (and `GET /status` reports
  `protocol_version: 1`). The two protocol versions must agree.
- [ ] In VoiceAttack, enable plugin support (**Options → General → "Enable plugin
  support"**) if not already on.
- [ ] **Import / re-point the profile.** Import `VAIVOX - VA Profile.vap`. Because the
  plugin **GUID changed** (ADR-0002, `{ED0BA443-726F-4A9F-AF05-DB400F39A501}`), re-point
  each command's *Execute an external plugin function* to the **VAIVOX** plugin — a
  one-time step. The command *names* (`Start Whisper Recording` / `Stop Whisper
  Recording`) are unchanged, so the bindings survive.
- [ ] **Bind your PTT**: bind a key/button to `Start Whisper Recording` (sends `start`)
  and the same key release to `Stop Whisper Recording` (sends `stop`), per the plugin
  README.
- [ ] **Restart VoiceAttack** so it loads the new DLL.
- [ ] Confirm VoiceAttack's log shows the **VAIVOX** plugin initialized (no load error) and
  that the listener bound port **65433**.

### 2.2 Return channel + API (VAIVOX side)

Edit `%LOCALAPPDATA%\VAIVOX\settings.cfg`:

- [ ] Enable the return channel (the kill-switch, default off):

  ```ini
  voiceattack_await_result = true
  # optional; default 0.3s — keep small so a stalled plugin never adds latency:
  # voiceattack_read_timeout = 0.3
  ```

- [ ] (For scenario (b) — auto-learning) enable auto-apply learning:

  ```ini
  vocab_auto_learn = true
  ```

  Leave it **off** (default) if you only want to observe near-miss *proposals* in the log
  rather than write `LEARNED` entries.

- [ ] (Optional, for scenario validation 5) set an LRU cap to exercise eviction:

  ```ini
  vocab_max_entries = 500     # caps every kind; DEFAULT seeds stay protected
  # vocab_grace_days = 7      # shields a just-stamped entry from eviction for N days
  ```

- [ ] Enable the introspection API for the read-outs:

  ```ini
  api_enabled = true
  # optional (defaults shown):
  # api_host = 127.0.0.1
  # api_port = 8765
  # api_token = your-token-here
  ```

  (You do **not** need `api_actions_enabled` for this runbook — every check here uses the
  read surface or the read-only `POST /reconcile/dry-run`. Enable it only if you want to
  drive `POST /reconcile/simulate` to dispatch without a mic.)

- [ ] **Start VAIVOX.** Confirm the startup log shows
  `Introspection API listening on http://127.0.0.1:8765` and that the control server bound
  port **65432**.
- [ ] **Liveness check** before going further:

  ```powershell
  Vget "/healthz"          # -> @{ status = ok }
  Vget "/status" | ConvertTo-Json -Depth 6   # version, recording=false, stt_backend, redacted config
  ```

- [ ] (Recommended) **Snapshot the baseline metrics** so each scenario's delta is obvious:

  ```powershell
  $before = Vget "/metrics"; $before | ConvertTo-Json
  ```

---

## 3. Smoke-test scenarios

Each scenario is **action → expected result → how to verify**. Run them in order; the
metrics deltas accumulate. The `match` / `not_found` bands only ever populate **because**
`voiceattack_await_result = true` and the replying plugin is installed — that is the whole
point of M5.

### (a) Nominal match — a known, valid command

- [ ] **Action:** Hold PTT and speak a command you **know** is valid in your current
  VAICOM/DCS context (e.g. a tower/ATC call your aircraft supports). Release.
  *(Example transcript used in the checks below: `two seven left` — substitute a real one
  for your install; see Assumptions.)*
- [ ] **Expected:** The VAIVOX UI shows `Sent text to VoiceAttack: <command>`; VoiceAttack
  executes the command and VAICOM acts on it; the plugin replies
  `{"v":1,"matched":true,"resolved_command":"..."}`, parsed into
  `MatchOutcome(matched=true)`.
- [ ] **Verify — the single most recent event matched:**

  ```powershell
  Vget "/reconciliations?limit=1" | ConvertTo-Json -Depth 8
  # events[-1].match.matched == True   (and .match.resolved_command set)
  ```

- [ ] **Verify — the `match` band moved, `unknown` did not:**

  ```powershell
  $after = Vget "/metrics"; $after | ConvertTo-Json
  # match increased by 1 vs $before; unknown UNCHANGED; match_rate > 0
  ```

- [ ] **Verify — telemetry persisted it:** the last line of
  `%LOCALAPPDATA%\VAIVOX\telemetry.jsonl` has `"match":{"matched":true,...}`:

  ```powershell
  Get-Content "$env:LOCALAPPDATA\VAIVOX\telemetry.jsonl" -Tail 1
  ```

### (b) No match — a deliberately wrong / near-miss command

- [ ] **Action:** Hold PTT and speak a command that is **close but invalid** — a slightly
  wrong callsign or a phrase VAICOM won't match (e.g. `towwer ground`). Release.
- [ ] **Expected:** The command is still sent; the plugin reports **not found**
  (`MatchOutcome(matched=false)`, `resolved_command` null). The phrase snapper may
  **abstain** and record a near-miss.
- [ ] **Verify — the event is not-matched + carries a near-miss:**

  ```powershell
  Vget "/reconciliations?limit=1" | ConvertTo-Json -Depth 8
  # events[-1].match.matched == False
  # events[-1].snap.decision == "abstained"  with snap.near_misses populated (if a phrase index is loaded)
  ```

- [ ] **Verify — the band moved:**

  ```powershell
  $after = Vget "/metrics"; $after | ConvertTo-Json
  # not_found increased (and/or abstain, if the snapper held it back); unknown UNCHANGED
  ```

- [ ] **Verify — auto-learn wrote a `LEARNED` entry** (only if `vocab_auto_learn = true`):

  ```powershell
  $v = Vget "/vocabulary"
  $v.by_kind.PSObject.Properties.Value | ForEach-Object { $_ } | Where-Object { $_.origin -eq "learned" }
  # a new entry with origin == "learned" should appear (its term = the near-miss surface form)
  ```

  With `vocab_auto_learn` **off** (default), no `LEARNED` entry is written — the proposal
  is only logged (`Vocabulary proposal: ...` in the VAIVOX log). That is the
  human-in-the-loop default.

### (c) Best-effort — old / non-replying plugin (or flag off)

This proves the compatibility matrix: a missing reply must **never** block or add
perceptible latency, and the band degrades to `unknown` (not an error).

- [ ] **Action:** Reproduce a non-replying peer in one of two ways:
  - swap the **old** (non-replying) DLL back into `<VoiceAttack>\Apps\VAIVOX\` and restart
    VoiceAttack; **or**
  - leave the new plugin but set `voiceattack_await_result = false` and restart VAIVOX.
  Then PTT a known-valid command.
- [ ] **Expected:** The command is dispatched normally; the UI shows the send; VAIVOX never
  hangs (the read either times out at ~`voiceattack_read_timeout` or is skipped entirely);
  the outcome is `unknown`.
- [ ] **Verify — no match signal, no latency regression:**

  ```powershell
  $after = Vget "/metrics"; $after | ConvertTo-Json
  # unknown increased by 1; match / not_found UNCHANGED
  Vget "/reconciliations?limit=1" | ConvertTo-Json -Depth 6
  # events[-1].match == $null
  ```

- [ ] **Verify — latency:** dispatch feels instant. With the flag *on* but the plugin not
  replying, the only cost is the bounded `voiceattack_read_timeout` (~0.3 s); with the flag
  *off* there is **zero** added cost (true fire-and-forget). Confirm subjectively that the
  command fires without a perceptible pause.

> Restore `voiceattack_await_result = true` and the **new** DLL before continuing, if you
> changed them here.

### (d) Kill-switch — flip the return channel off at runtime

- [ ] **Action:** Set `voiceattack_await_result = false` in `settings.cfg` and **restart
  VAIVOX** (config is read at startup). PTT a known command.
- [ ] **Expected:** Immediate return to fire-and-forget — the sink never reads the reply,
  zero added latency, exactly the legacy behaviour. The plugin still writes its reply; the
  app simply closes the socket without reading it, and the plugin tolerates the broken pipe
  (wrapped write).
- [ ] **Verify:**

  ```powershell
  $after = Vget "/metrics"; $after | ConvertTo-Json
  # unknown increased; match / not_found UNCHANGED (same as scenario (c))
  ```

- [ ] Re-enable (`voiceattack_await_result = true`) + restart for the AC5 check.

---

## 4. Acceptance criterion AC5

> *After real usage with the new plugin, on `GET /metrics` the `unknown_rate` drops toward
> ~0 and `match_rate` / `not_found_rate` become meaningful.*

- [ ] With `voiceattack_await_result = true` and the **replying** plugin installed, run a
  realistic session: PTT **a couple dozen** commands (a healthy mix of valid commands and a
  few deliberate near-misses), so the metrics window is populated by real outcomes.
- [ ] **Read the metrics:**

  ```powershell
  Vget "/metrics" | ConvertTo-Json
  ```

  ```bash
  # curl equivalent
  curl -s http://127.0.0.1:8765/metrics
  ```

- [ ] **Observe (the AC5 gate):**
  - `match` and `not_found` are **non-zero** and account for nearly every event:
    `match_rate + not_found_rate ≈ 1.0`.
  - `unknown` is **near 0** for events dispatched **with the channel on** (i.e. an
    `unknown_rate` trending to ~0 across the new-plugin session). Pre-channel events still
    sitting in the window count as `unknown` — read it as a trend, or clear/rotate
    `telemetry.jsonl` before the AC5 run for a clean window.
  - `wrong_match` stays ~0 (the eval guards this offline; here it confirms the plugin
    resolves to the command we dispatched — `resolved_command` matches `sent_text`).

  > **Contrast with today (no channel):** `/metrics` reports `unknown` dominating and
  > `match` = 0, because the outcome was never reported. AC5 is exactly the inversion of
  > that picture.

- [ ] **Pass:** `unknown_rate → ~0`, `match_rate` and `not_found_rate` meaningful,
  `wrong_match` ~0. Record the numbers in the release notes.

---

## 5. Validate the learning loop in the field

Confirm the closed loop end-to-end: a real match signal drives stamping; near-misses
become `LEARNED`; a cap evicts LRU `LEARNED` while protecting seeds.

- [ ] **Stamping (`hits` / `last_used` climb on matches):** note an entry's stats, PTT a
  command that exercises it a few times, re-read:

  ```powershell
  Vget "/vocabulary" | ConvertTo-Json -Depth 6
  # the matched entry's hits increased and last_used advanced (stamping is now MATCH-gated,
  # not dispatch-proxy: only matched==true credits usage)
  ```

  Cross-check: an entry used in a **not-matched** utterance (scenario (b)) should **not**
  gain a hit — that is the match-gating working.
- [ ] **`LEARNED` entries created** (needs `vocab_auto_learn = true`): after a few
  near-misses, `GET /vocabulary` lists new entries with `origin == "learned"` (see (b)).
  These are the captured near-miss → nearest-valid-phrase mappings.
- [ ] **Eviction** (needs `vocab_max_entries` set, §2.2): once `LEARNED` entries exceed the
  cap, the LRU pass evicts the **least-recently-used `LEARNED`** entry on the next stamping
  pass; **every `DEFAULT` (seed) entry stays present** regardless of the cap, and a
  just-used entry inside `vocab_grace_days` is shielded. Verify by checking that the
  `learned` count stops growing past the cap while the `default` set is intact:

  ```powershell
  $v = Vget "/vocabulary"
  $all = $v.by_kind.PSObject.Properties.Value | ForEach-Object { $_ }
  "learned: " + ($all | Where-Object origin -eq learned).Count
  "default: " + ($all | Where-Object origin -eq default).Count
  ```

---

## 6. Rollback

If the new plugin misbehaves (latency, crashes, bad matches):

- [ ] Copy the **previous** `VaivoxVAPlugin.dll` back into `<VoiceAttack>\Apps\VAIVOX\`
  (keep the prior DLL in the release for exactly this).
- [ ] Set `voiceattack_await_result = false` in `settings.cfg` (instant kill-switch — the
  sink falls back to fire-and-forget even with a bad plugin still installed).
- [ ] **Restart VoiceAttack** (and VAIVOX, so the flag takes effect).
- [ ] Verify you are back to the legacy picture: `/metrics` `unknown` resumes growing,
  `match` / `not_found` stop moving, dispatch latency is zero. No data loss — telemetry and
  vocabulary are unaffected by the rollback.

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Invoke-RestMethod` / `curl` → **connection refused** on the API | API not enabled, or wrong host/port | Set `api_enabled = true`; confirm `api_host`/`api_port` (default `127.0.0.1:8765`) match your call; confirm the startup log printed `Introspection API listening on ...`. |
| API returns **401** | `api_token` is set but the header is missing | Send `Authorization: Bearer <token>` on every request (set `$Token` in the helper). |
| Mutating action (`/vocabulary/...`, `/reconcile/simulate`) returns **403** | `api_actions_enabled` is off | Set `api_actions_enabled = true` and restart. Not needed for this runbook's read-only checks. |
| **No command fires** in VoiceAttack at all | Control/listener socket not connected (ports **65432** / **65433**), or another app holds the port | Check the VAIVOX log bound **65432** and the plugin bound **65433**; ensure no stale VAIVOX/upstream instance is holding them; restart both. |
| Plugin **not loaded** by VoiceAttack | Plugin support off, DLL in the wrong folder, or wrong .NET | Enable plugin support; DLL must be at `<VoiceAttack>\Apps\VAIVOX\VaivoxVAPlugin.dll`; confirm it is the **net48 Release** build; check VoiceAttack's log for a load error. |
| Command fires but the **plugin reference is stale** ("plugin not found" in VA) | GUID changed (ADR-0002) and the `.vap` was not re-pointed | Re-point each command's *Execute an external plugin function* to the **VAIVOX** plugin (§2.1). |
| `/metrics` keeps showing **`unknown`** even with the new plugin | The reply is never read | Confirm `voiceattack_await_result = true` **and** VAIVOX was restarted after the edit; confirm the **replying** (M4) DLL is installed, not an old one; check `voiceattack_read_timeout` isn't absurdly low. |
| `match` populates but **`wrong_match` rises** | Plugin resolves to a different command than dispatched | Inspect `/reconciliations` — compare `match.resolved_command` vs `sent_text`; usually a VAICOM/profile mapping issue, not VAIVOX. |
| No `snap.near_misses` ever recorded | No phrase index loaded (the snapper is a no-op) | Generate the VAICOM vocabulary (`POST /vocabulary/generate`, or the startup background refresh) so `phrase_index.txt` exists in `%LOCALAPPDATA%\VAIVOX`. |
| No `LEARNED` entries despite near-misses | `vocab_auto_learn` is off (propose-only default) | Set `vocab_auto_learn = true` and restart; or read the proposals from the VAIVOX log instead. |

---

## Assumptions to validate on your real install

- **Exact DCS/VAICOM command strings** for scenarios (a)/(b): the runbook uses
  `two seven left` (valid) and `towwer ground` (near-miss) as **placeholders**. Replace
  them with commands your current aircraft/theatre actually supports — the match outcome is
  only meaningful against your real VAICOM keyword set.
- **PTT binding**: assumes a press→`Start Whisper Recording`, release→`Stop Whisper
  Recording` mapping. Adjust to your VoiceAttack binding style.
- **`api_port` / `api_host`**: examples assume the defaults `127.0.0.1:8765`. If you
  overrode them in `settings.cfg`, update `$Api` in the helper.
- **Old DLL availability** for scenario (c)/Rollback: assumes you kept a prior
  (non-replying) build. If you never had one, use the `voiceattack_await_result = false`
  path to exercise the best-effort/kill-switch case instead.
- **Clean metrics window for AC5**: if pre-channel `unknown` events are still in the
  window, either read `unknown_rate` as a trend or rotate `telemetry.jsonl` before the AC5
  run.
