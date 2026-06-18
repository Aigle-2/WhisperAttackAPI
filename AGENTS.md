# VAIVOX — agent & contributor guide

VAIVOX turns push-to-talk speech into DCS radio commands on top of **VoiceAttack 2**
+ **VAICOM Community** (Windows desktop app). It is a divergence of WhisperAttackAPI,
mid-rewrite from an amateur layout to a hexagonal one. Decisions live in
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
- **Next — Phase 4:** identity & rebrand (`ProductIdentity`, VAIVOX naming, new GUID,
  `%LOCALAPPDATA%\VAIVOX`, ports); stop shipping VAICOM-derived data (ADR-0005).

During the migration the legacy top-level modules (`whisper_attack.py`,
`whisper_server.py`, `configuration.py`, `stt_backends/`, …) are thin re-export/launcher
**shims that delegate into `src/vaivox/`** (the single source of truth). `whisper_attack.py`
now just launches `vaivox.main`; `whisper_server.py` is superseded and kept only as a
short-lived rollback reference. New behavior goes in `src/vaivox/`.

## Quality gates (ADR-0007)

Strict gates are scoped to the new `src/vaivox/` tree. Legacy modules are excluded
(ruff `extend-exclude`) or loosened (mypy per-module `ignore_errors`) so the gates are
green without rewriting code a later phase will move. Run them all from the repo root:

```bash
ruff check .                # lint
ruff format --check .       # formatting (Google-convention docstrings via D rules)
mypy                        # strict, scoped to src/vaivox
pytest                      # unit / architecture tests (add --cov=vaivox for coverage)
PYTHONPATH=src lint-imports --config pyproject.toml   # architecture contracts
```

The architecture contracts also run in-process inside `pytest`
(`tests/architecture/test_layering.py`).

## Dev setup

```bash
pip install -e .[dev]       # toolchain + runtime deps
pre-commit install          # optional: run the gates on commit
```

Running from source uses a small `sys.path` shim in `vaivox.main` (and the
`whisper_attack.py` launcher) so the in-repo `src/vaivox` package is importable; the
PyInstaller build targets `src/vaivox/main.py` and passes `--paths src`. Tests get `src`
via the pytest `pythonpath` setting — no install required just to run the gates.

## Conventions

- **Python 3.10+** (`X | None` typing is used). Type everything in `src/vaivox/`; mypy is
  strict there.
- **Google-style docstrings** on public modules/classes/functions in `src/vaivox/`.
- **Tests** live under `tests/{unit,contract,integration,architecture}`; the
  docstring/annotation rules are relaxed for them. The STT **contract test**
  (`tests/contract/test_stt_contract.py`) pins every adapter to the `SpeechToText` port.
  When changing reconciliation behavior, update the **golden characterization tests** in
  `tests/unit/test_reconciliation.py` deliberately — they pin parity with the original
  implementation.
- Don't reformat or tighten types on legacy modules just to satisfy a gate; they're
  excluded on purpose until their migration phase.
