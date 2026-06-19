# VAIVOX — agent & contributor guide

VAIVOX turns push-to-talk speech into DCS radio commands on top of **VoiceAttack 2**
+ **VAICOM Community** (Windows desktop app). It is a divergence of WhisperAttackAPI,
mid-rewrite from a legacy layout to a hexagonal one. Decisions live in
[`docs/adr/`](docs/adr/); the phased roadmap is [`docs/MIGRATION_PLAN.md`](docs/MIGRATION_PLAN.md).

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
    the same mission stays quiet; the F10 reader is session-scoped (`mission_f10.py` baselines
    the log at startup) so a restart purges the overlay instead of re-pulling stale imports.
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
  evidence and makes future threshold/scoring changes safer.
- Don't reformat or tighten types on the `tools/` scripts just to satisfy a gate; they're
  excluded on purpose (utility code, not part of the strict tree).
