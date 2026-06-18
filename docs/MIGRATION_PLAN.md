# VAIVOX — Migration Plan

From the amateur-grade WhisperAttackAPI layout to a hexagonal, SOLID, tooled
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

### Phase 3 — Ports, use cases, adapters
Define the driven ports; move STT/audio/VA/kneeboard/inbound into adapters; add the
use cases and `composition.py`; `main.py` becomes the only entry point. Add an STT
**contract test** run against every adapter (LSP). Land a minimal read-only
**introspection API** (status + `dry-run reconcile`, ADR-0010) so agentic debugging
is available from here on.
**Exit:** app runs end-to-end on the new architecture at full parity; integration
tests pass.

### Phase 4 — Identity & rebrand
Introduce `ProductIdentity` (VAIVOX, new GUID, `%LOCALAPPDATA%\VAIVOX`, ports,
titles). Rebrand the C# plugin + bundled `.vap`. README courtesy note. Stop
shipping VAICOM-derived data; add auto-discovery + background generation + generic
seed (ADR-0005).
**Exit:** no `WhisperAttack`/upstream-GUID/old-port references remain; fresh install
works out-of-the-box via the seed and self-generates VAICOM vocabulary.

### Phase 5 — Reconciliation features (on clean seams)
- **A — Governance** (ADR-0004): JSONL vocab + usage sidecar + `VocabularyGovernor`
  + Tier 1/2 attribution; **reload model** (ADR-0009): idle-gated hot atomic swap.
- **C — Telemetry** (ADR-0006): plugin return channel + `TelemetrySink` + report.
- **B — Phrase snap** (Axis B): phrase index + conservative whole-utterance snap
  with abstain (same scorer as the near-miss top-N).
- **Eval harness** (ADR-0008): LLM dataset + VAICOM mock + metrics, CI-gated.
- **Agent API + skills** (ADR-0010): enrich the introspection API
  (telemetry / vocab / metrics endpoints + MCP adapter) and ship the agent
  skill / prompts.
Order: A and C first (C's "entry fired" event powers A's recency), then B (which
relies on telemetry to tune thresholds safely).
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
