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
                     (stt, audio, voiceattack, kneeboard, inbound, api, config, ui, …)
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
  *Deferred follow-ups:* ADR-0005 **background** generation on first run + the in-app
  "Refresh VAICOM vocabulary" control (auto-discovery + the generator itself now exist —
  see Phase 5); and the C# `dotnet` build / `.vap` re-point (verified by hand, not in CI).
- **Phase 5** 🚧 (in progress) the reconciliation features, on clean seams:
  - **A — Governance** (ADR-0004) ✅ core: `domain/vocabulary/` `VocabularyEntry` +
    `VocabularyGovernor` (rank by recency/hits, LRU eviction with DEFAULT protection +
    grace window, Tier 1 token-provenance attribution), the `VocabularyRepository` port,
    and a JSONL source + usage-sidecar adapter.
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
    (unit-tested on synthetic fixtures; end-to-end needs a real install). *Deferred:*
    recipient segmentation; thresholds-in-settings.
  - **Agent API/MCP** (ADR-0010) ✅ read API: introspection endpoints `/status`,
    `/metrics`, `/reconciliations`, `/vocabulary` + `POST /reconcile/dry-run` over query
    use cases (off by default, localhost, optional bearer token, secrets redacted), plus
    the `vaivox-debug` Claude Code skill. *Deferred:* the MCP server adapter (needs the
    `mcp` dependency) and gated mutating actions (reload / generate / simulate).
  - **Cross-cutting blocker:** the C# plugin **return channel** (ADR-0006) gates the
    match-signal-dependent work — live usage stamping (`mark_used`/recency), near-miss
    capture, Tier 2 attribution — and needs a Windows/VoiceAttack build (not CI-testable).

During the migration the remaining legacy top-level modules (`whisper_attack.py`,
`configuration.py`, `transcription_postprocess.py`, `stt_backends/`) are thin
re-export/launcher **shims that delegate into `src/vaivox/`** (the single source of truth).
`whisper_attack.py` now just launches `vaivox.main`. The fully-migrated god-module and UI
modules (`whisper_server.py`, `writer.py`, `theme.py`, `word_mappings.py`) were **deleted**
in the Phase 5 cleanup — their behavior lives in `infrastructure/ui/` + the use cases. New
behavior goes in `src/vaivox/`.

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
uv run vaivox               # launch the app (needs --extra app or full)
```

Running from source uses a small `sys.path` shim in `vaivox.main` (and the
`whisper_attack.py` launcher) so the in-repo `src/vaivox` package is importable; the
PyInstaller build (`build_exe.ps1`) targets `src/vaivox/main.py` and passes `--paths src`.
`uv sync` installs `vaivox` editable, so `import vaivox` and `lint-imports` work without
extra path setup; the pytest `pythonpath` setting still exposes the legacy top-level
shims.

## Runtime introspection API (ADR-0010)

For fast debug — *why did command X not fire?* — VAIVOX exposes a **read-only localhost
HTTP/JSON introspection API** over the `application/queries.py` use cases (a driver
adapter in `infrastructure/api/introspection.py`, stdlib `http.server`, no extra
dependency). It is **off by default**, binds **127.0.0.1 only**, never mutates state,
never returns secrets (config via the redacted accessor), and takes an **optional
bearer token**. Enable it in the per-user `settings.cfg` with `api_enabled = true`
(optional `api_host` / `api_port` / `api_token`).

Endpoints: `GET /healthz`, `GET /status`, `GET /metrics` (match/wrong-match/not-found/
unknown/abstain counts + rates over recorded telemetry), `GET /reconciliations?limit=N`
(recent provenance), `GET /vocabulary` (entries + usage by kind), and the killer
`POST /reconcile/dry-run {"text": "..."}` (full pipeline, no mic/VoiceAttack).

The full debug recipes (curl examples, the dry-run workflow, deferred MCP adapter +
mutating actions) live in the Claude Code skill
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
- Don't reformat or tighten types on legacy modules just to satisfy a gate; they're
  excluded on purpose until their migration phase.
