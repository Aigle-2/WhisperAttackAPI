# VAIVOX — Migration Plan

From the legacy WhisperAttackAPI layout to a hexagonal, SOLID, tooled
codebase, then onto the three reconciliation features. Decisions are recorded in
[adr/](adr/).

## Constraints & principles

- **Branch-first.** All work happens on `refactor/vaivox-hexagonal` in the current
  repo. A clean public repo is created only at publication (ADR-0003).
- **No fork users yet** → no backward-compat or data-migration debt toward upstream.
- **Parity before features.** The app must reach functional parity on the new
  architecture *before* axes A/B/C are built. We refactor first so features land on
  clean seams.
- **Each phase is independently verifiable** (tests green, app launches and
  records → transcribes → routes a command).

## Target package layout

```
src/vaivox/
├── domain/                     # pure, no I/O (import-linter: imports nothing outward)
│   ├── reconciliation/         # pipeline, normalization, numbers, spelled-codes,
│   │                           # fuzzy, snapper (Axis B), model (VOs)
│   ├── vocabulary/             # VocabularyEntry, Governor (Axis A), keyterms,
│   │                           # repository (port)
│   ├── telemetry/              # ReconciliationOutcome / NearMiss value objects
│   └── shared/                 # errors
├── application/                # use cases + driven-port interfaces
│   ├── ports.py                # SpeechToText, AudioRecorder, CommandSink,
│   │                           # KneeboardSink, TelemetrySink, Clock, ConfigProvider
│   ├── record_command.py       # StartRecording / StopAndReconcile
│   └── shutdown.py
├── infrastructure/             # adapters (the only layer that touches the outside)
│   ├── stt/                    # elevenlabs / openai / deepgram / faster_whisper + factory
│   ├── audio/                  # sounddevice/soundfile recorder
│   ├── voiceattack/            # socket sink (+ inbound result channel, ADR-0006)
│   ├── kneeboard/              # pyperclip + keyboard
│   ├── inbound/                # control-socket server (start/stop/shutdown)
│   ├── api/                    # HTTP/JSON + MCP introspection adapters (ADR-0010)
│   ├── vocabulary/             # JSONL source repo + usage sidecar (ADR-0004)
│   ├── telemetry/              # JSONL sink (ADR-0006)
│   ├── config/                 # settings.cfg reader + ProductIdentity (ADR-0002)
│   └── ui/                     # ttkbootstrap window, pystray tray, writer, theme,
│                               # word-mapping modal
├── composition.py              # dependency injection / wiring
└── main.py                     # bootstrap entry point

plugin/VaivoxVAPlugin/          # C# plugin, new GUID (ADR-0002), dotnet build
tools/                          # generate_vaicom_keyterms.py (+ phrase index, ADR-0005)
tests/  unit/  integration/  architecture/
packaging/                      # PyInstaller spec + build.py
docs/  adr/  MIGRATION_PLAN.md
```

## File mapping (current → target)

| Current | Target |
|---------|--------|
| `whisper_server.py` (god-module) | split: `infrastructure/inbound/`, `infrastructure/audio/`, `domain/reconciliation/`, `infrastructure/voiceattack/`, `infrastructure/kneeboard/`, `application/record_command.py` |
| `transcription_postprocess.py` | `domain/reconciliation/normalization.py` |
| `stt_backends/base.py` | port → `application/ports.py`; result VO → `domain/reconciliation/model.py` |
| `stt_backends/*_backend.py`, `factory.py`, `http_utils.py`, `prompts.py` | `infrastructure/stt/` |
| `stt_backends/keyterms.py` | `domain/vocabulary/keyterms.py` |
| `stt_backends/vaicom_keyterms.txt` | **removed from VCS** (ADR-0005); generated locally |
| `configuration.py` | `infrastructure/config/settings.py` + a domain config VO |
| `word_mappings.py`, `writer.py`, `theme.py` | `infrastructure/ui/` |
| `whisper_attack.py` | `infrastructure/ui/` (window+tray) + `main.py` + `composition.py` |
| `tools/generate_vaicom_keyterms.py` | stays; extended to emit the phrase index |
| `VoiceAttackPlugin/WhisperAttack/` | `plugin/VaivoxVAPlugin/` (new GUID) |
| `build_*.cmd`, `build_exe.ps1` | `packaging/` + `build.py` + CI |
| `requirements*.txt` | `pyproject.toml` (`[full]` extra) |

## Phases

### Phase 0 — Decisions & plan ✅ (this change)
ADRs + this plan, on the branch.
**Exit:** decisions reviewed and accepted.

### Phase 1 — Scaffolding (no behavior change)
`pyproject.toml`, ruff/mypy/pytest/pre-commit, GitHub Actions, empty `src/vaivox/`
tree, `import-linter` contracts, the test-pyramid skeleton
(unit/contract/integration/architecture, ADR-0008), port the existing tests. The
app still runs from the old modules.
**Exit:** CI green; `import-linter` passes on the empty layers; app unchanged.

### Phase 2 — Extract the domain
Move reconciliation (normalize, numbers, spelled-codes, fuzzy) and the vocabulary
model into `domain/`, pure and fully unit-tested. Old modules call into the new
domain.
**Exit:** domain has no I/O imports; unit tests cover the pipeline; behavior parity.

### Phase 3 — Ports, use cases, adapters ✅
Defined the driven ports (`application/ports.py`); moved STT/audio/VA/kneeboard/inbound/
config/UI into `infrastructure/` adapters; added the use cases (`record_command`,
`shutdown`, `queries`) and `composition.py`; `vaivox.main` is now the only entry point
(wired as the `vaivox` console script and the PyInstaller target). An STT **contract
test** runs against every adapter (LSP), and a minimal read-only **introspection API**
(status + `POST /reconcile/dry-run`, ADR-0010 — off by default, localhost) is in place.
The legacy top-level modules are thin re-export/launcher shims that delegate into
`src/vaivox/`.
**Exit:** ✅ app runs end-to-end on the new architecture at full parity (verified via
the use-case integration tests through fakes); contract + integration tests pass; all
gates green.

### Phase 4 — Identity & rebrand ✅ (core)
Introduced `ProductIdentity` (`infrastructure/config/identity.py`: VAIVOX, fresh GUID,
`%LOCALAPPDATA%\VAIVOX`, log, ports, titles) and routed `main`/UI/composition/settings
through it. Renamed the new-tree classes off the upstream brand, rebranded the build
artifact + release assets + docs (README courtesy/attribution note added), and moved the
C# plugin to `plugin/VaivoxVAPlugin/` with a fresh GUID. Stopped shipping
VAICOM-derived data (ADR-0005): the loader reads a locally-generated file from
`%LOCALAPPDATA%\VAIVOX` and falls back to a generic non-VAICOM seed so a fresh install
works out-of-the-box.
**Exit:** ✅ no `WhisperAttack` product-identity / upstream-GUID references remain in the
new tree (only attribution + screenshot filenames); seed works out-of-the-box; gates
green. **Deferred:** the C# `dotnet` build + bundled `.vap` re-point (binary; done by hand
in VoiceAttack, not verifiable in CI). The VAICOM auto-discovery, the keyterm/phrase-index
generator, and ADR-0005 **background** generation on first run / on stale all now exist
(see Phase 5); only the UI "Refresh VAICOM vocabulary" **button** remains.

### Phase 5 — Reconciliation features (on clean seams) 🚧 (in progress)
- **A — Governance** (ADR-0004) ✅ core: `domain/vocabulary/` model + `VocabularyGovernor`
  (rank by recency/hits, LRU eviction with DEFAULT protection + grace window, Tier 1
  attribution), `VocabularyRepository` port, JSONL source + usage-sidecar adapter.
  *Deferred:* Tier 2 counterfactual; live `mark_used` wiring (blocked on the match
  signal, below). The **reload model** (ADR-0009) idle-gated hot atomic swap shipped for
  the **phrase index** (`infrastructure/reload/` + the `PhraseMatcher` port; swapped only
  when not recording, observable, eval still frozen); the **vocabulary** swap + file-watch
  remain (they wait on the pipeline reading vocab from `VocabularyRepository`).
- **C — Telemetry** (ADR-0006) ✅ §1 ("always"): `JsonlTelemetrySink` +
  config-gated wiring. *Deferred:* the **plugin return channel** (`MatchOutcome`) —
  needs the C# rebuild — and with it usage stamping and near-miss capture.
- **Eval harness** (ADR-0008) ✅: `tests/eval/` VAICOM mock + curated golden dataset +
  metrics + committed baseline gate (`wrong_match == 0`). *Deferred:* the LLM-generated
  dataset augmentation (the human-curated golden set is in place).
- **B — Phrase snap** (ADR-0011) ✅: conservative three-band `PhraseSnapper` with abstain
  (same scorer as the near-miss top-N), live-wired into `StopAndReconcile` + recorded in
  telemetry (no-op until a phrase index exists). The eval recovers every near-miss with
  `wrong_match == 0` held. The keyterm + phrase-index **generator**
  (`tools/generate_vaicom_keyterms.py`, ADR-0005) auto-discovers a VAICOM install and emits
  both files to `%LOCALAPPDATA%\VAIVOX` (unit-tested on synthetic fixtures; end-to-end
  needs a real install). *Deferred:* recipient segmentation; thresholds-in-settings.
- **Agent API + skills** (ADR-0010) ✅ read API **+ gated actions**: the localhost
  introspection API serves `/status`, `/metrics`, `/reconciliations`, `/vocabulary` +
  `POST /reconcile/dry-run` over read-only query use cases, plus the **mutating actions**
  `POST /vocabulary/generate` | `/vocabulary/reload` | `/reconcile/simulate` gated behind
  `api_actions_enabled` (off by default, 403 otherwise; `route_command` shared with the PTT
  flow). Off by default, bearer token, redacted; shipped with the `vaivox-debug` Claude
  Code skill. *Deferred:* the MCP server adapter (needs the `mcp` dependency).
Order: A and C landed first (C's "entry fired" event powers A's recency), then B (which
relies on the eval/telemetry to tune thresholds safely). The match-signal-dependent
pieces (A's recency, C's outcome, near-miss) wait on the C# return channel.
**Exit:** a committed reconciliation **metric** (match / wrong-match / abstain) with
no regression, and a measurable drop in `not found` without wrong-command snaps.

## Risk notes

- **Hidden behavior in the god-module.** Mitigate by characterization tests on the
  current cleanup/fuzzy output *before* moving code in Phase 2.
- **STT adapters drift from the port.** The Phase 3 contract test pins the
  contract (normalized result, typed errors).
- **Auto-discovery misses non-standard VAICOM installs.** Mitigate with the path
  override + clear UI status (ADR-0005).
- **Wrong phrase snap fires the wrong DCS command.** Conservative threshold +
  abstain; never snap below confidence (Axis B / ADR-0006 telemetry to calibrate).
