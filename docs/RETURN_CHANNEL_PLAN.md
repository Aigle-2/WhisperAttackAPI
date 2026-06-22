# Return channel — implementation, test & deployment plan (ADR-0006)

Closing the reconciliation loop: the C# plugin reports the VoiceAttack match outcome
back to VAIVOX, which unblocks live metrics, match-gated usage stamping, and the
**vocabulary learning loop** (near-miss → `LEARNED` entries → governance/eviction).

This plan is built around two hard constraints of the repo:

- The plugin is C# and **cannot run in CI** (CI is Linux; no VoiceAttack/VAICOM/DCS).
- The plugin today is a single `.cs` with **no project file** and is **not bundled** in
  the release (`build_exe.ps1` ignores it) — build + install are fully manual.

## Governing principles

1. **Contract-first.** Freeze the wire protocol as a versioned artifact with shared
   golden vectors; both sides are then tested independently against it.
2. **Ports are the test seams.** The match outcome re-enters the application **through a
   port** — `CommandSink.send(command) -> MatchOutcome | None`. The adapter is **pure
   transport** (send bytes, read reply, parse). **No learning logic lives in the
   adapter.** This is what makes the learning loop testable with in-memory fakes, no
   sockets, no Windows.
3. **Learning is a use case, not adapter code.** The near-miss → `LEARNED` path is an
   application use case driven by the repository/clock ports — so it is proven in CI on
   Linux **before** any C# exists.
4. **Best-effort.** Short read timeout; on no/garbled reply the outcome is `unknown`,
   telemetry still records, nothing is stamped, the user is never blocked.
5. **Two deploy cadences, decoupled.** Ship the Python side first (harmless against an
   old plugin: `unknown`), then the plugin. A config kill-switch gates reply-reading.

## Acceptance criteria (Definition of Done)

- **AC1 — Contract frozen.** Wire protocol + a committed golden-vectors file consumed by
  both the Python and the C# test suites.
- **AC2 — Learning loop is end-to-end testable in memory (headline).** The full loop
  (utterance → reconcile → snap → dispatch → match outcome → stamping + near-miss →
  `LEARNED` → eviction) has an **application-level test with STT and VAICOM mocked at the
  port level, no socket, no Windows**, green in **CI Linux**.
- **AC3 — Adapter plumbing tested.** The real `VoiceAttackCommandSink` round-trips against
  a **fake-plugin TCP server** fixture (matched / not-found / slow>timeout / garbage /
  closed-without-reply / refused), in CI Linux.
- **AC4 — C# unit tested.** `BuildReply` / `Decide` pass against the same golden vectors,
  in a CI `dotnet` job.
- **AC5 — Validated in the field.** After deploy on a real install, `/metrics`
  `unknown_rate` drops toward ~0 and `match_rate` / `not_found_rate` become meaningful.

## Wire protocol (frozen, M1)

> **Frozen (M1).** The reference Python implementation is
> `src/vaivox/infrastructure/voiceattack/protocol.py` (`build_reply` /
> `parse_match_outcome`, `MATCH_PROTOCOL_VERSION = 1`); the shared golden vectors are
> `tests/contract/match_protocol_vectors.json` and are exercised by
> `tests/unit/test_match_protocol.py`. The serialization is **compact** (no
> inter-token whitespace) with a **stable key order** `v`, `matched`,
> `resolved_command` so the C# plugin (M4) can emit byte-identical replies. Example:
> `build_reply(True, "Tower, request taxi")` →
> `b'{"v":1,"matched":true,"resolved_command":"Tower, request taxi"}\n'`. The parser
> is best-effort: empty / invalid-JSON / non-object / missing-or-non-boolean
> `matched` → `None` (unknown); unknown fields are ignored (forward-compatible); a
> non-string `resolved_command` is coerced to `null`.

| Aspect | Decision |
|---|---|
| Connection | Reuse the existing **65433** socket, same connection (request then reply, then close) |
| Request | Unchanged: the command text, UTF-8 |
| Reply | **One `\n`-terminated UTF-8 JSON line**: `{"v":1,"matched":true,"resolved_command":"..."}` (`resolved_command` may be `null`) |
| Framing | Read **until `\n`** — never a single `recv` (TCP may split/coalesce) |
| Versioning | `"v"` integer; unknown fields are ignored (forward-compatible) |
| Timeout | Short read timeout (e.g. 300 ms) on the Python side; expiry → `unknown` |

**Compatibility matrix** (must hold — this is what makes staged deploy safe):

| App \ Plugin | Old plugin (no reply) | New plugin (replies) |
|---|---|---|
| **Old app** (doesn't read) | current behaviour ✓ | plugin writes, app closes without reading → plugin **must tolerate broken pipe** (wrap `Write` in try/catch) |
| **New app** (best-effort read) | timeout → `unknown` ✓ | nominal: `MatchOutcome` populated ✓ |

**Golden vectors:** `tests/contract/match_protocol_vectors.json` — `{input, reply_bytes}`
pairs, the single source of truth for both languages' serialization/parsing tests.

## Architecture changes (the seams)

1. **Port change:** `CommandSink.send(self, command: str) -> MatchOutcome | None`
   (kneeboard sink is untouched — notes are never matched).
2. **`route_command`** receives the `MatchOutcome` from the sink and threads it into:
   - `ReconciliationOutcome.match` (telemetry), and
   - the `UsageStamper`, now **gated on `match.matched is True`** (replaces today's
     dispatch-proxy stamping).
3. **New learning use case** — `LearnFromOutcome` (application), port-driven:
   - inputs: the `ReconciliationResult` + `SnapResult` near-misses + the `MatchOutcome`
     + `VocabularyRepository` + `Clock`.
   - on **not matched / snap abstained**: derive a *proposal* (pure domain function:
     utterance + nearest valid phrases → a suggested mapping/alias) and, per an
     **apply policy**, either record the proposal for human review (default) or write a
     `LEARNED` entry via `repository.add(entry, when)`.
   - the policy is a flag (default: proposals only, human-in-the-loop per ADR-0006);
     tests flip it to auto-apply, or call the apply step directly.
4. **Orchestration point:** `StopAndReconcile` and `SimulateUtterance` already share the
   single `route_command` path — the `MatchOutcome` is fanned out to the stamper **and**
   `LearnFromOutcome` there, so there is exactly one place that learns.
5. **Maintenance (eviction):** the existing `UsageStamper` LRU pass (`govern` +
   `replace_entries`) stays as-is — it activates automatically once `LEARNED` entries
   exist and a cap is configured.

## Test strategy by layer

| Layer | What | Runs in | Proves |
|---|---|---|---|
| **0. Contract** | golden vectors shared by Python + C# | both CI jobs | the two implementations never drift |
| **1. Python unit** | `parse_match_outcome(bytes)`: valid / matched / not-matched / missing fields / bad JSON / empty / extra fields | CI Linux | parsing + forward-compat |
| **2. Learning loop (headline, AC2)** | fake `SpeechToText` + fake `CommandSink` returning scripted `MatchOutcome`; **real** repo on `tmp_path`; **fake `Clock`**; real `VocabularyGovernor` | **CI Linux** | stamping on match, near-miss → `LEARNED`, eviction, grace window, abstain — **the learning logic**, no socket |
| **3. Adapter plumbing (AC3)** | **fake-plugin TCP server** fixture vs the real `VoiceAttackCommandSink.send()` | CI Linux | framing (`\n`), timeout, best-effort fallback, reset — the **socket client** |
| **4. C# unit (AC4)** | `BuildReply` / `Decide` vs golden vectors; `ICommandProbe` fake | CI `dotnet` | serialization + match decision |
| **5. E2E manual (AC5)** | runbook on a real Windows + VoiceAttack install | by hand, pre-release | the real VoiceAttack integration |

**Do not conflate layers 2 and 3.** Layer 2 tests *the learning* and needs **no socket**
(it drives the use cases with port fakes — `SimulateUtterance` already gives the
"STT-mocked full path"). Layer 3 tests *the plumbing* of the one adapter that talks TCP.
The learning is proven a full layer above the wire.

### Sketch of the layer-2 learning test

```python
repo   = JsonlVocabularyRepository(tmp_path)          # real store, real state
clock  = FakeClock(start=...)                          # deterministic time
sink   = FakeCommandSink(queue=[...])                  # "VAICOM mocked": scripted MatchOutcome
# STT mocked = drive via SimulateUtterance (text in directly), or a FakeSpeechToText

loop = build_learning_path(repo, clock, sink, governor=VocabularyGovernor(), policy=AUTO_APPLY)

loop.run("two seven left", MatchOutcome(matched=True,  resolved_command="..."))
loop.run("towwer ground",  MatchOutcome(matched=False))            # → near-miss

assert repo.load(WORD_MAPPING)[id].usage.hits == 1                 # stamped only on match
assert any(e.entry.origin is LEARNED for e in repo.load(...))      # near-miss → LEARNED
clock.advance(grace_window + 1); loop.maintain(max_entries=N)      # eviction pass
assert default_entries_all_present()                              # DEFAULT protected
assert evicted == [the_least_recently_used_learned]               # LRU order correct
```

Everything is port-driven: **STT and VAICOM are fully mocked, no network, no VoiceAttack.**

## C# tooling prerequisites (M4)

- **`plugin/VaivoxVAPlugin/VaivoxVAPlugin.csproj`** — `net48` class library. Because the
  plugin talks to VoiceAttack only through `dynamic vaProxy`, **no `VoiceAttack.dll`
  reference is needed to compile** → it builds (and unit-tests) without VoiceAttack
  installed. (The README's "csproj not committed, depends on local SDK" no longer holds.)
- **Refactor for testability:** extract pure functions free of `vaProxy`:
  `static string BuildReply(bool matched, string? resolvedCommand)` and
  `MatchResult Decide(ICommandProbe probe, string text)` where `ICommandProbe` wraps
  `Command.Exists`/`Command.Execute`. The socket handler becomes a thin shell.
- **`plugin/VaivoxVAPlugin.Tests/`** — xUnit, asserts `BuildReply`/`Decide` against the
  golden vectors.

## CI

- **Keep** the Linux Python job (covers layers 0, 1, 2, 3).
- **Add** a `dotnet` job on `windows-latest`: `dotnet build` + `dotnet test` (layer 4 +
  a standing guarantee the plugin compiles — nothing checks that today). Full VoiceAttack
  E2E stays manual (irreducible).

## Deployment

1. **Commit the `.csproj`** and document the no-reference build. ✅ (M4)
2. **Bundle the plugin in the release** ✅ (M6): `build_exe.ps1` calls `build_plugin.ps1`
   (`dotnet build plugin/VaivoxVAPlugin.sln -c Release`) and copies `VaivoxVAPlugin.dll`
   **and** `VAIVOX - VA Profile.vap` into the release under `Apps/VAIVOX/` (mirroring the
   install target `<VoiceAttack>\Apps\VAIVOX\`); both are added to the post-build
   `$ExpectedReleaseItems` check. The zip now ships app + plugin + profile. A missing .NET
   SDK is a **hard fail** by default (the official release must include the plugin);
   `build_exe.ps1 -SkipPlugin` is the explicit app-only escape hatch.
3. **Version stamp** ✅ (M6): the plugin carries an explicit `<Version>`/`<AssemblyVersion>`/
   `<FileVersion>` and a `MatchProtocolVersion` constant equal to Python's
   `MATCH_PROTOCOL_VERSION` (= 1; asserted via the shared golden vectors). Both sides log it
   at startup — the plugin's `VA_Init1` writes `VAIVOX plugin <ver>, match protocol v1` to
   the VA log; the Python composition logs `Return channel: match protocol v1,
   await_result=...` and `GET /status` exposes `protocol_version`.
4. **Kill-switch:** `voiceattack_await_result` in `settings.cfg` — disables reply-reading
   instantly if a bad plugin adds latency (the sink falls back to fire-and-forget).
5. **Staged rollout:** ship Python first (safe: old plugin → `unknown`), then the plugin;
   metrics start populating. **Rollback:** keep the prior DLL in the release, re-copy +
   restart VoiceAttack, flag off.
6. **Runbook** (in `plugin/README.md`): unzip → copy DLL to `<VoiceAttack>\Apps\VAIVOX\`
   → import/re-point the `.vap` → restart VoiceAttack → PTT smoke test.

> **Single-user (current case):** you control both sides, so you can skip the canary and
> just rebuild + copy + restart; the compatibility matrix and kill-switch are still a
> cheap safety net. **If you distribute:** the matrix and the flag become mandatory
> (mixed plugin/app versions in the wild).

## Milestones

| # | Milestone | CI? | Notes |
|---|---|---|---|
| **M1** ✅ | Freeze the wire protocol + commit golden vectors | n/a | zero behaviour change — `protocol.py` + `match_protocol_vectors.json` + `test_match_protocol.py` |
| **M2** | **Seams + learning loop, fully tested in memory (AC2).** Port change `CommandSink.send -> MatchOutcome\|None`; thread the outcome through `route_command`; match-gated stamping; the `LearnFromOutcome` use case; the layer-2 learning test (fake sink/STT). | **Linux** | **the learning logic is proven before any C# exists** — the sink still returns `None` (no socket yet), the loop is exercised via the fake sink |
| **M3** | Python adapter: real sink reads the reply best-effort (returns `MatchOutcome\|None`) + fake-plugin TCP integration tests (AC3) | **Linux** | plumbing only |
| **M4** | C#: `.csproj` + testability refactor + xUnit vs golden vectors + CI `dotnet` job (AC4) | **Windows** | closes the "C# not in CI" gap for compile+unit |
| **M5** | Manual E2E on a real install — the [**E2E runbook**](RETURN_CHANNEL_E2E_RUNBOOK.md) (AC5) | manual | the only step needing VoiceAttack |
| **M6** 🚧 | **Bundle plugin in the release + version stamp** ✅ (`build_plugin.ps1` + `build_exe.ps1` → `Apps/VAIVOX/`, assembly+protocol version logged both sides); staged deploy + flip the flag + watch `/metrics` (manual, on a real install); optionally enable the auto-apply learning policy | manual | field validation |

**M1 and M2 are doable now, entirely in CI, without touching Windows** — and by the end
of M2 the learning loop is fully implemented and proven; M3–M5 only feed it a *real*
match signal in place of the fake one.
