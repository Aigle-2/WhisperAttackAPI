# VAIVOX — agent & contributor guide

VAIVOX turns push-to-talk speech into DCS radio commands on top of **VoiceAttack 2**
+ **VAICOM Community** (Windows desktop app). It is a divergence of WhisperAttackAPI,
mid-rewrite from a legacy layout to a hexagonal one. Decisions live in
[`docs/adr/`](docs/adr/); the phased roadmap is [`docs/MIGRATION_PLAN.md`](docs/MIGRATION_PLAN.md).
An **optional**, mission-specific voice-call reference — for missions that bundle the
community MOOSE "AI ATC" script — lives in
[`docs/AI_ATC_EXAMPLE_CALLS.md`](docs/AI_ATC_EXAMPLE_CALLS.md) (most missions don't include it).

## Architecture (ADR-0001): hexagonal, dependencies point inward

```
src/vaivox/
├── domain/          pure logic, NO I/O (reconciliation, vocabulary, telemetry, shared)
├── application/     use cases (record_command, shutdown, queries) + driven ports
└── infrastructure/  adapters — the only layer touching the outside world
                     (stt, audio, voiceattack, kneeboard, inbound, api, config, ui,
                      reload, …)
    composition.py / main.py   wiring + the single entry point
```

The **dependency rule** is enforced by `import-linter` (contracts in `pyproject.toml`):

- `domain` must not import `application` or `infrastructure`.
- `application` must not import `infrastructure`.

Domain code may import pure third-party libraries (e.g. `rapidfuzz`, `text2digits`)
but never anything that does I/O (sockets, files, mic, network, UI).

## Migration status

- **Phase 0** ✅ ADRs + plan.
- **Phase 1** ✅ Scaffolding: `pyproject.toml`, tooling, empty `src/vaivox/` tree, CI.
- **Phase 2** ✅ Domain extracted: `domain/reconciliation/` (normalization, numbers,
  spelled-codes, fuzzy, pipeline, model) and `domain/vocabulary/keyterms.py`. The legacy
  modules now **delegate** to the domain (single source of truth).
- **Phase 3** ✅ Ports, use cases, adapters. Driven ports in `application/ports.py`
  (`SpeechToText`, `AudioRecorder`, `CommandSink`, `KneeboardSink`, `StatusReporter`,
  `TelemetrySink`, `Clock`, `ConfigProvider`); use cases (`record_command`, `shutdown`,
  `queries`); adapters under `infrastructure/` (`stt`, `audio`, `voiceattack`,
  `kneeboard`, `inbound`, `config`, `ui`, `api`, `telemetry`, `vocabulary`).
  `composition.py` wires everything and `vaivox.main` is the single entry point
  (`vaivox` console script). An STT **contract test** runs against every adapter and a
  minimal **introspection API** (status + `POST /reconcile/dry-run`, off by default,
  localhost) ships per ADR-0010.
- **Phase 4** ✅ Identity & rebrand. `ProductIdentity`
  (`infrastructure/config/identity.py`) is the single source of name/GUID/data-dir/log/
  ports/titles (ADR-0002/0003); `main`, the UI, composition, and settings resolve
  through it. New-tree classes renamed off the upstream brand (`VaivoxConfiguration`,
  `VaivoxApp`, `VaivoxWordMappings`); build artifact, assets, plugin, and docs are
  VAIVOX. The C# plugin moved to `plugin/VaivoxVAPlugin/` with a fresh GUID. VAICOM-
  derived data is no longer shipped (ADR-0005): the loader reads a locally-generated
  file from `%LOCALAPPDATA%\VAIVOX` and falls back to a generic non-VAICOM seed.
  *Deferred follow-ups:* the in-app "Refresh VAICOM vocabulary" **button** (auto-discovery,
  the generator, and ADR-0005 **background** generation on first run now all exist — see
  Phase 5; the button is a thin `RefreshVocabulary.execute(force=True)` call); and the C#
  `dotnet` build / `.vap` re-point (verified by hand, not in CI).
- **Phase 5** 🚧 (in progress) the reconciliation features, on clean seams:
  - **A — Governance** (ADR-0004) ✅ core: `domain/vocabulary/` `VocabularyEntry` +
    `VocabularyGovernor` (rank by recency/hits, LRU eviction with DEFAULT protection +
    grace window, Tier 1 token-provenance attribution), the `VocabularyRepository` port,
    and a JSONL source + usage-sidecar adapter. A one-shot migration
    (`infrastructure/vocabulary/migration.py` + `tools/migrate_vocabulary.py`) seeds the
    JSONL source from the legacy `fuzzy_words.txt` / `word_mappings.txt`.
  - **C — Telemetry** (ADR-0006) ✅ §1: `JsonlTelemetrySink` appends each
    `ReconciliationOutcome` to `%LOCALAPPDATA%\VAIVOX`, config-gated (`telemetry_enabled`,
    default on).
  - **Eval harness** (ADR-0008) ✅: `tests/eval/` — VAICOM match-oracle mock, a curated
    golden dataset, metrics (match / wrong-match / abstain) + a committed baseline gate;
    the decisive guard is `wrong_match == 0`.
  - **B — Phrase snap** (ADR-0011) ✅: conservative three-band `PhraseSnapper`
    (snap / abstain+near-miss / raw, runner-up margin), wired into `StopAndReconcile`
    (VoiceAttack path only) + recorded in telemetry; a no-op until a phrase index exists.
    The eval recovers every near-miss with `wrong_match == 0` held. The keyterm +
    phrase-index **generator** (`tools/generate_vaicom_keyterms.py`, ADR-0005)
    auto-discovers a VAICOM install and emits both files to `%LOCALAPPDATA%\VAIVOX`
    (unit-tested on synthetic fixtures; end-to-end needs a real install). The `HIGH` /
    `LOW` / `MARGIN` thresholds are overridable in `settings.cfg` (`snap_high` / `snap_low`
    / `snap_margin`); the composition injects the builder so a hot-reload keeps the
    calibration. *Deferred:* recipient segmentation.
  - **Background vocabulary generation** (ADR-0005) ✅: `RefreshVocabulary`
    (`application/refresh_vocabulary.py`) over the `VocabularyGenerator` port +
    `VaicomVocabularyGenerator` adapter (lazy/defensive wrap of the `tools/` generator)
    runs on a daemon thread at startup — regenerates when missing/stale (outputs absent or
    install sources newer), reports status, and **hot-applies** the new phrase index via
    the reload seam below. *Deferred:* the UI "Refresh" button (`force=True`); bundling the
    generator into the frozen build; live keyterm reload (STT loads keyterms at startup).
  - **Reload model** (ADR-0009) ✅ phrase index: an idle-gated atomic swap — the generic
    `IdleGatedSwap[T]` + `ReloadablePhraseSnapper` (`infrastructure/reload/`) swap a
    regenerated phrase index in **only when not recording** (never mid-utterance), behind
    the new `application.ports.PhraseMatcher` port, reporting "Vocabulary refreshed: N
    phrases"; exposed on `WiredApp.phrase_snapper` for a reload trigger. The eval stays on
    a frozen `PhraseSnapper` (no leak). *Deferred:* the vocabulary swap (waits on the
    pipeline reading vocab from `VocabularyRepository`), the LRU pass, and the file-watch.
  - **Command browser + mission pull log** (UI) ✅: a toolbar **Commands** button opens a
    non-modal window (`infrastructure/ui/commands_window.py`) with **Core** and **F10** tabs
    — the live permanent vocabulary (`WiredApp.get_core_phrases`) and the mission F10 overlay
    (`WiredApp.get_mission_phrases`) respectively — each sorted alphabetically with a live
    search box (filter, arrow-key nav, horizontal scroll, Enter to focus/copy). Each tab
    polls its source so a vocabulary refresh or an F10 poll updates it in place. The mission
    F10 poll (`RefreshMissionVocabulary`) reports a **count-only** line on each changed pull
    — `N commands pulled, X new (M total)` — diffing against the previous poll so re-polling
    the same mission stays quiet; the overlay is scoped to the latest `Mission title:` block
    in the log (`mission_f10.py`), with a whole-log fallback when that block holds no F10 so
    the current mission's commands still surface across a restart. A `mission_f10_verbose_logging`
    setting (Settings window toggle) makes each poll emit a detailed diagnostic block —
    resolved log path + size, mission markers, current-mission vs whole-log match counts,
    fallback used, and the pulled commands — to debug an empty F10 overlay. F10 entries expose
    **command surfaces**: the human label uses the bare menu name (`MORMON MESA 8`) while
    VAICOM's internal identifier (`Action MORMON MESA 8`) and dispatch metadata are preserved
    for typed routing (`VaicomF10Action`), so `mission_f10.py` strips only for labels/aliases. The
    VoiceAttack sink now surfaces the plugin's return-channel match result (`VoiceAttack
    matched: …` / `VoiceAttack has no command for: …`), so an unrecognized phrasing is visible
    rather than silent. The phrase-index
    generator splits CommandStrings on top-level `;` only (keeping `[Alpha;Bravo]` alternation
    groups intact) and keeps balanced `[...]` parameter slots, so the Core list shows clean
    commands like `Radar Focus Target [1..20]`.
  - **Command surfaces + typed dispatch** (ADR-0012) ✅ *(amended 2026-06-20)*:
    `domain/commands/` resolves reconciled text to a `CommandSurface` with a typed target
    before legacy snap fallback. Whole-query exact matching is followed by a conservative
    embedded-label phase for realistic full radio calls: only contiguous live F10 labels
    with at least two normalized tokens qualify, the unique most-specific label wins, and
    equal specificity abstains. Single-token callsigns/numbers therefore require an exact
    whole utterance, except for the exact anchored grammar `Set call sign|callsign <label>`,
    which may select a unique nonnumeric live F10 label (`Set call sign Chaos` → `Chaos`).
    This does not admit trailing composite digits, so `DREAM 7` wins inside a clearance call
    and an embedded `7` cannot hijack it.
    Static commands dispatch their command name through the
    VoiceAttack sink; live F10 surfaces fire DCS `missionCommands.doAction(ActionIndex)` over
    a UDP datagram (`UdpVaicomF10ActionSink` → `127.0.0.1:33491`, settings
    `vaicom_f10_host`/`vaicom_f10_port`), replicating VAICOM's own
    `mission.player.actionsequence` path — F10 items are **not** VoiceAttack commands (zero
    `Action …` entries in any profile), so they take a separate transport. A single
    `ActionIndex` fires nested items. The authoritative index is the **live DCS menu**: a
    VAIVOX-owned panel hook (`infrastructure/dcs/`, `DcsHookInstaller` self-heals it into the
    radio panel on every startup so it survives DCS/VAICOM updates) scans the authoritative
    `data.menuOther` tree that VAICOM itself exports as `menuaux`, then broadcasts the current
    path-aware protocol-v2 menu snapshots over UDP to `MissionMenuListener` (port `33493`).
    Snapshots carry a DCS-process session id and menu revision; v7 also re-sends the settled
    snapshot every 5 seconds at the same revision, so relaunching VAIVOX after DCS recovers
    the live handshake without trusting disk or restarting DCS. An active listener ignores
    the duplicate revision without invalidating its handles. The listener debounces changed
    menus, rejects stale revisions and ambiguous duplicate labels, and never restores its
    diagnostic disk mirror for dispatch. `mission_f10.py` clears every unreliable whole-log
    `Set menu F10 item` index before applying that live map, so a missing handshake or label
    fails closed (`Command ID` and historical indices are diagnostic only). Every incoming
    mutation invalidates the old map immediately, and `UdpVaicomF10ActionSink` resolves the
    label from the settled map again at send time to close the resolve-to-dispatch race.
    F10 dispatch is fire-and-forget (no `match`); telemetry records `resolution` + typed
    `dispatch`. When no surface resolves, the legacy snapper picks a static
    `VoiceAttackCommand`. The earlier "F10 via a VoiceAttack `Action …` alias" amendment was
    a dead end and is removed. Transport confirmed live (`actionsequence:[0]` fired
    FLEX NORTH); live v5 validated the namespace fix and protocol handshake but showed DCS
    bypassed late `clearOtherMenu` / `addOtherCommand` replacements, so v6 scans
    `data.menuOther` on a throttled GUI callback; v7 adds the restart-safe heartbeat. Live
    capture is **validated**: revision 3
    delivered 88 path-aware commands with no ambiguity and VAIVOX persisted the identical
    DCS session (`FLEX NORTH=0`, `MORMON MESA 8=5`). Spoken end-to-end dispatch is also
    validated through UDP: real ElevenLabs output `Voice command assist` resolved to the
    mission surface, re-read current index 6 at send time, and emitted accepted typed F10
    dispatch. DCS provides no acknowledgement, so the final mission effect is operator-observed.
    The DCS install dir is auto-discovered via registry + the Steam library owning app id
    223750; `dcs_install_dir` is an override. If a hook (re)install happens while DCS is
    running (`is_dcs_running`), VAIVOX **red-alerts** (modal + red status) to order a DCS
    restart — the stale loaded panel could otherwise misfire. Full source-cited write-up in
    [`docs/VAICOM_F10_EXECUTION_CONTRACT.md`](docs/VAICOM_F10_EXECUTION_CONTRACT.md).
  - **Agent API/MCP** (ADR-0010) ✅ read API **+ gated actions + MCP**: introspection
    endpoints `/status`, `/metrics`, `/reconciliations`, `/vocabulary` + `POST
    /reconcile/dry-run` over query use cases (off by default, localhost, optional bearer
    token, secrets redacted), plus the `vaivox-debug` Claude Code skill. The **mutating
    actions** (`POST /vocabulary/generate` | `/vocabulary/reload` | `/reconcile/simulate`)
    go through application use cases and are gated behind `api_actions_enabled` (off by
    default, 403 otherwise); `route_command` is shared so simulate dispatches identically to
    the PTT flow. The **MCP server adapter** (`infrastructure/api/mcp_server.py` +
    `vaivox-mcp` console script) serves the *same read query use cases* as FastMCP stdio
    tools — `mcp` is an optional extra, imported lazily so the gate stays dep-light. *Scope:*
    the MCP server is a read-only reader process; mutating actions stay on the HTTP API.
  - **Return channel** (ADR-0006) ✅ both sides: the C# plugin (`plugin/VaivoxVAPlugin/`)
    replies one JSON line `{ text, matched, resolved_command }` on the command socket right
    after `Command.Exists` (before `Command.Execute`); `VoiceAttackCommandSink.send` reads it
    (short timeout; EOF/timeout/malformed → unknown, so an un-rebuilt plugin keeps parity),
    and `route_command` records it in `ReconciliationOutcome.match` and — on a match — stamps
    **live usage** via Tier 1 attribution (`mark_used`/recency). Attribution is a surface-form
    Tier 1 proxy today (the pipeline still reads vocab from `config`, not the repository);
    near-miss capture into telemetry (`SnapSummary.near_misses`) already lands on every
    abstain. The plugin builds from a committed `VaivoxVAPlugin.csproj` (net8.0).
    *Hardware-gated remainder (not CI-testable):* deploy the rebuilt DLL + re-point
    `VAIVOX - VA Profile.vap` (ADR-0002) + the DCS smoke; then the follow-ups it unblocks —
    the offline near-miss review report and Tier 2 counterfactual attribution (both want
    accumulated live match data and the pipeline reading vocab from `VocabularyRepository`).

`src/vaivox/` is the single source of truth and the only application code: the legacy
top-level shims (`whisper_attack.py`, `configuration.py`, `transcription_postprocess.py`,
`stt_backends/`) and the god-module / UI modules (`whisper_server.py`, `writer.py`,
`theme.py`, `word_mappings.py`) have all been **deleted** — their behavior lives in
`domain/` + the use cases + `infrastructure/`. The only code outside the strict tree is
`tools/` (the VAICOM generator + the vocabulary migration). New behavior goes in
`src/vaivox/`.

## Quality gates (ADR-0007)

Strict gates are scoped to the new `src/vaivox/` tree. Legacy modules are excluded
(ruff `extend-exclude`) or loosened (mypy per-module `ignore_errors`) so the gates are
green without rewriting code a later phase will move. Run them all from the repo root
with **uv** (it provisions the pinned Python and the locked toolchain on first run):

```bash
uv run ruff check .                       # lint
uv run ruff format --check .              # formatting (Google-convention docstrings)
uv run mypy                               # strict, scoped to src/vaivox
uv run lint-imports --config pyproject.toml   # architecture contracts
uv run pytest --cov=vaivox                # unit / contract / integration / architecture
```

The architecture contracts also run in-process inside `pytest`
(`tests/architecture/test_layering.py`).

## Dev setup

The project is managed by **[uv](https://docs.astral.sh/uv/)** and targets **Python
3.12** (pinned in `.python-version`; every dependency is frozen in `uv.lock`).

```bash
uv sync                     # gate essentials: core deps + the `dev` group, on 3.12
pre-commit install          # optional: run the gates on commit
```

`uv sync` deliberately installs only what the gates need — the pure core deps
(`rapidfuzz`, `text2digits`) plus the `dev` group. The GUI/audio/network runtime is
opt-in because its libraries are imported lazily:

```bash
uv sync --extra app         # + ttkbootstrap/sounddevice/keyboard/... (run the real app)
uv sync --extra full        # + torch/faster-whisper/transformers (local STT)
uv sync --extra mcp         # + the `mcp` SDK (the vaivox-mcp agent server, ADR-0010)
uv run vaivox               # launch the app (needs --extra app or full)
uv run --extra mcp vaivox-mcp   # serve the read-only MCP introspection tools over stdio
```

Running from source uses a small `sys.path` shim in `vaivox.main` so the in-repo
`src/vaivox` package is importable; the PyInstaller build (`build_exe.ps1`) targets
`src/vaivox/main.py` and passes `--paths src`. `uv sync` installs `vaivox` editable, so
`import vaivox` and `lint-imports` work without extra path setup; the pytest `pythonpath`
setting also exposes the repo root so the `tools/` scripts import.

## Runtime introspection API (ADR-0010)

For fast debug — *why did command X not fire?* — VAIVOX exposes a **localhost HTTP/JSON
introspection API** over the `application/` use cases (a driver adapter in
`infrastructure/api/introspection.py`, stdlib `http.server`, no extra dependency). It is
**off by default**, binds **127.0.0.1 only**, never returns secrets (config via the
redacted accessor), and takes an **optional bearer token**. The read surface never mutates
state; the mutating actions are **additionally gated** off by default. Enable it in the
per-user `settings.cfg` with `api_enabled = true` (optional `api_host` / `api_port` /
`api_token`, and `api_actions_enabled = true` to opt into the actions).

Read endpoints: `GET /healthz`, `GET /status`, `GET /metrics` (match/wrong-match/not-found/
unknown/abstain counts + rates over recorded telemetry), `GET /reconciliations?limit=N`
(recent provenance), `GET /vocabulary` (entries + usage by kind), and the killer
`POST /reconcile/dry-run {"text": "..."}` (full pipeline, no mic/VoiceAttack). **Gated
mutating actions** (403 unless `api_actions_enabled`): `POST /vocabulary/generate`
(regenerate from VAICOM + hot-apply), `POST /vocabulary/reload` (re-read the index from
disk + hot-apply), `POST /reconcile/simulate {"text": "..."}` (reconcile **and dispatch**
for real).

For **native** agent tooling, the same read query use cases are also served as MCP stdio
tools by the `vaivox-mcp` console script (`infrastructure/api/mcp_server.py` +
`src/vaivox/mcp_main.py`): a standalone read-only reader process over the persisted state.
`mcp` is an optional extra (`uv sync --extra mcp`), imported lazily so the default gate sync
stays dependency-free.

The full debug recipes (curl examples, the dry-run workflow, the gated actions, the MCP
`.mcp.json` setup) live in the Claude Code skill
[`.claude/skills/vaivox-debug/SKILL.md`](.claude/skills/vaivox-debug/SKILL.md).

## Conventions

- **Python 3.12** (single supported version; `requires-python = ">=3.12"`, ruff/mypy
  target 3.12). Type everything in `src/vaivox/`; mypy is strict there.
- **Google-style docstrings** on public modules/classes/functions in `src/vaivox/`.
- **Tests** live under `tests/{unit,contract,integration,architecture}`; the
  docstring/annotation rules are relaxed for them. The STT **contract test**
  (`tests/contract/test_stt_contract.py`) pins every adapter to the `SpeechToText` port.
  When changing reconciliation behavior, update the **golden characterization tests** in
  `tests/unit/test_reconciliation.py` deliberately — they pin parity with the original
  implementation.
- Whenever an agent gets access to a real-life example of STT prediction, phrase
  snapping, VoiceAttack result, near-miss, wrong match, or abstain behavior, add it to
  the relevant test dataset before or alongside the fix. Prefer the eval fixtures in
  `tests/eval/` for end-to-end reconciliation/snap outcomes and focused unit/integration
  tests for narrow regressions. This keeps the dataset growing from actual operator
  evidence and makes future threshold/scoring changes safer. For mission-F10 ATC
  phraseology specifically, the optional reference
  [`docs/AI_ATC_EXAMPLE_CALLS.md`](docs/AI_ATC_EXAMPLE_CALLS.md) documents example calls and
  is already seeded into the `tests/eval/` fixtures (tagged `ai_atc` / `mission_f10`).
- Don't reformat or tighten types on the `tools/` scripts just to satisfy a gate; they're
  excluded on purpose (utility code, not part of the strict tree).
