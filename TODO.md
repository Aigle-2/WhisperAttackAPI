# VAIVOX — remaining tasks

A living punch-list of what's left after Phases 0–5 (core). The phased narrative lives in
[`docs/MIGRATION_PLAN.md`](docs/MIGRATION_PLAN.md); decisions are in [`docs/adr/`](docs/adr/).
At last update the tree is green: **243 tests**, ruff / format / mypy / import-linter all
pass via `uv run` (see [AGENTS.md](AGENTS.md)).

**Done so far (Phase 5):** A governance core (ADR-0004), C telemetry persistence
(ADR-0006 §1), the eval harness (ADR-0008), B phrase-snap (ADR-0011), the VAICOM
keyterm + phrase-index generator with auto-discovery + **background generation on first
run / on stale** (ADR-0005), the **idle-gated phrase-index hot-reload** (ADR-0009), and the
introspection API — read endpoints + **gated mutating actions** + the **MCP server
adapter** (`vaivox-mcp`) + `vaivox-debug` skill (ADR-0010).

---

## 1. Blocked — needs a Windows + VoiceAttack + DCS machine (not CI-testable)

The reconciliation return loop (ADR-0006) is now **implemented on both sides** and the
VoiceAttack 2 plugin is deployed on the dev rig. The live bridge has been smoke-tested
through VoiceAttack: the VAIVOX plugin initializes, listens on `65433`, press/release
actions drive the VAIVOX app on `65432`, recording starts/stops, STT returns text, and
VAIVOX sends the command back to VoiceAttack. What remains here is the actual
**DCS/VAICOM in-game smoke** that proves `matched=true` / `matched=false` telemetry and
usage stamping against a live mission.

- [x] **C# plugin return channel (ADR-0006) — code done.**
  `plugin/VaivoxVAPlugin/VaivoxVAPlugin.cs` replies `{ text, matched, resolved_command }` on
  the same socket (before `Command.Execute`); `VoiceAttackCommandSink.send` reads it (short
  timeout, EOF/timeout/malformed → unknown) and `route_command` populates
  `ReconciliationOutcome.match`. Tested with in-memory fakes + a real-socket round-trip.
  *Hardware-gated:* the DCS smoke below still needs to see match outcomes live.
- [x] **Live usage stamping / recency (ADR-0004) — code done.** On a matched outcome
  `route_command` runs Tier 1 attribution and calls
  `VocabularyRepository.mark_used(credited_ids, clock.now())`. *Reachable scope:* attribution
  is a surface-form Tier 1 proxy today — the live pipeline reads vocab from `config` (not the
  repository) and emits no per-edit provenance, so an entry is credited when its canonical
  term survives into the matched command; precise per-edit provenance waits on the pipeline
  reading vocab from `VocabularyRepository`. Activated by the DCS smoke below.
- [ ] **Near-miss capture (ADR-0006 §3).** The snapper already records near-misses into
  telemetry (`SnapSummary.near_misses`) on every abstain. *Remaining:* the offline
  review/report that proposes new mappings/aliases from frequent not-founds — needs
  accumulated live match data (so it follows the DCS smoke below).
- [ ] **Tier 2 counterfactual attribution (ADR-0004).** Pipeline-replay + phrase-index
  oracle on ambiguous matches. Larger; needs the match signal **and** the pipeline reading
  vocab from `VocabularyRepository` (so attribution can credit by exact edit, not surface form).
- [x] **C# `dotnet` build + deploy — done on the dev rig.** `VaivoxVAPlugin.csproj`
  targets `net8.0`, matching the VoiceAttack 2 plugin contract; it built **0 warnings / 0
  errors** with a .NET 8 SDK. `VaivoxVAPlugin.dll` + `VaivoxVAPlugin.deps.json` were
  deployed to both `%APPDATA%\VoiceAttack2\Apps\VAIVOX\` (VA 2.1.8+ preferred third-party
  plugin location) and `...\VoiceAttack 2\Apps\VAIVOX\`. VoiceAttack logs confirm
  `Plugin 'VAIVOX' initialized` and `VAIVOX listener started`.
- [x] **VoiceAttack profile/action re-point smoke — done on the dev rig.** TX5
  press/release actions were corrected to invoke the **VAIVOX** plugin with contexts
  `Start VAIVOX Recording` / `Stop VAIVOX Recording`. Live result: VAIVOX starts/stops
  recording, transcribes `Radio Check`, and logs `Sent text to VoiceAttack: Radio Check`.
  Note: because `.vap` exports are binary/encrypted, fresh imports still need this GUI
  validation step.
- [ ] **DCS end-to-end smoke (ADR-0006/0002).** With VoiceAttack + VAICOM + DCS: PTT a known
  command → fires in-game + `matched=true` + a usage hit in `%LOCALAPPDATA%\VAIVOX\
  <kind>.usage.json` + `GET /metrics` shows a real `match`; PTT an unknown command →
  `matched=false` + near-miss recorded + no stamp. Recipe in
  `plugin/VaivoxVAPlugin/README.md`.
- [ ] **Generator end-to-end (ADR-0005).** Run `python tools/generate_vaicom_keyterms.py`
  against a real VAICOM install; verify the emitted `%LOCALAPPDATA%\VAIVOX\vaicom_keyterms.txt`
  + `phrase_index.txt` shape (the phrase index must line up with VoiceAttack's actual
  command strings) and that the snapper improves matches with `wrong_match == 0` held.
  *Progress:* the packaged app generated live VAICOM vocabulary on the dev rig
  (`1437` phrases, `850` keyterms) and hot-applied `1437` phrases; the remaining check is
  comparing the generated phrases against active VoiceAttack commands / snapper behavior.
- [ ] **Phase 3/4 runtime validation.** The GUI window/tray, the real socket/audio/keyboard
  adapters, the PyInstaller build (`build_exe.ps1`), and the uv-based CI were verified *by
  construction* but never executed. *Progress:* the built app has now run on the dev rig:
  GUI, vocabulary refresh, control socket, VoiceAttack socket, audio recording lifecycle,
  STT, and command send-back all worked. Remaining: tray behavior, a clean-machine zip
  install, and the DCS smoke above.

## 2. Buildable in CI — no hardware required

- [x] **MCP server adapter (ADR-0010).** `infrastructure/api/mcp_server.py`
  (`IntrospectionTools` + `build_mcp_server`) exposes the *same* read query use cases as
  the HTTP API (status / dry-run / recent / metrics / vocabulary) as FastMCP tools, served
  over **stdio** by the `vaivox-mcp` console script (`vaivox/mcp_main.py`, headless reader
  process). `mcp` is an **optional extra** imported **lazily** (the gate stays dep-light;
  the smoke test imports every module mcp-free — verified). Tool bodies unit-tested without
  `mcp`; the FastMCP build + headless wiring validated against the real SDK (`--extra mcp`).
  *Scope:* read/reproduce only — the mutating actions stay on the embedded HTTP API (they
  act on live in-app state a separate reader process doesn't own).
- [x] **Gated mutating API actions (ADR-0010).** `POST /vocabulary/generate` (force
  regenerate + hot-apply), `/vocabulary/reload` (re-read index from disk + hot-apply), and
  `/reconcile/simulate` (reconcile **and dispatch** for real) over the `RefreshVocabulary` /
  `ReloadVocabulary` / `SimulateUtterance` use cases. Gated behind `api_actions_enabled`
  (off by default, 403 otherwise); `route_command` is shared with `StopAndReconcile` so
  simulate dispatches identically to the PTT path. Reload/generate go through the ADR-0009
  idle-gated swap. Tested over real HTTP (403-by-default + each action enabled).
- [x] **Background generation on first run / on stale (ADR-0005).** `RefreshVocabulary`
  (`application/refresh_vocabulary.py`) gates on the `VocabularyGenerator` port's
  `is_stale()` (outputs missing, or a discovered install's sources newer than them),
  generates via `VaicomVocabularyGenerator` (lazy/defensive wrap of
  `tools/generate_vaicom_keyterms.py`), and **hot-applies** the regenerated phrase index
  through the ADR-0009 reload seam. `VaivoxApp` runs it on a daemon thread at startup; it
  reports status and falls back to the seed when no install is found. Unit-tested with the
  generator faked (trigger logic + status) + the adapter's staleness branches. *Follow-ups:*
  keyterms apply on next launch (STT loads them at startup, not hot); bundle/migrate the
  generator into the frozen build (today it degrades to "generator unavailable" in a
  packaged exe — see "Generator end-to-end" in §1); the UI "Refresh" button is a thin
  `execute(force=True)` call (still part of ADR-0005 item 4 below).
- [ ] **Vocabulary / index hot-reload (ADR-0009)** — *phrase index ✅; vocab swap +
  file-watch deferred.* The idle-gated atomic swap **mechanism** shipped: the generic
  `IdleGatedSwap[T]` (`infrastructure/reload/idle_gated.py`) + `ReloadablePhraseSnapper`
  swap a regenerated phrase index in **only when not recording** (never mid-utterance,
  in-flight `snap` keeps its captured reference) and report "Vocabulary refreshed: N
  phrases". The snapper is wired through it (`build_phrase_snapper`) behind the new
  `PhraseMatcher` port and exposed on `WiredApp.phrase_snapper` for a reload trigger to
  call (#3 background-gen / the #4 reload action). The eval still builds a frozen
  `PhraseSnapper`, so nothing leaks into the metrics. *Remaining:* extend the swap to the
  vocabulary once the pipeline reads word-mappings/fuzzy from `VocabularyRepository`
  (today it reads them from `config`), the LRU maintenance pass, and the optional JSONL
  file-watch (ADR-0009 action item 3).
- [ ] **Governance maintenance wiring (ADR-0004).** Wire `VocabularyGovernor.govern`
  (eviction) into a maintenance pass + `VocabularyRepository.replace_entries`. Meaningful
  only once usage data exists (depends on live stamping above).
- [x] **`.txt → JSONL` vocab migration (ADR-0004 action item).** `migrate_legacy_vocabulary`
  + the pure `legacy_to_entries` (`infrastructure/vocabulary/migration.py`) convert the
  merged `fuzzy_words.txt` / `word_mappings.txt` into structured `VocabularyEntry` records
  (aliases grouped by replacement, slug ids, `DEFAULT` origin) and seed them through the
  repository; one-shot CLI `tools/migrate_vocabulary.py`, idempotent by id. Tested (converter
  + a real repo round-trip) and validated end-to-end on the repo defaults (21 fuzzy + 48
  mappings). *Follow-up:* auto-run on first launch waits on the pipeline reading vocab from
  the repository (today the live pipeline still reads from `config`).
- [ ] **Phrase-snap follow-ups (ADR-0011)** — *thresholds-in-settings ✅; recipient
  segmentation deferred.* The `HIGH` / `LOW` / `MARGIN` thresholds are now overridable in
  `settings.cfg` (`snap_high` / `snap_low` / `snap_margin`, defaults = the eval-calibrated
  constants); the composition injects the builder into `ReloadablePhraseSnapper` so a
  hot-reload keeps the configured calibration. *Remaining:* recipient-segment the phrase
  index + snapper (v1 is whole-phrase `token_sort_ratio`).
- [ ] **Eval dataset augmentation (ADR-0008).** Add the LLM-generated tagged dataset
  alongside the human-curated golden set; consider a small real-audio smoke anchor.

## 3. Docs / process / publication

- [ ] **Confirm VAICOM-Community's license (ADR-0005 action item 5)** to validate the
  generator-only posture and the generic seed's provenance.
- [ ] **At publication (ADR-0003):** check GitHub repo/org + Discord name availability; the
  repo rename is deferred until a clean public repo is created.
- [ ] **Add the README courtesy note's links** are live / correct at publication time.

---

_Update this file as items land (and prefer adding a new ADR over editing decisions). The
C# return channel has now shipped and the VoiceAttack bridge is live on the dev rig;
section 1's remaining work is the DCS/VAICOM in-game smoke, then the follow-ups it
unblocks (the near-miss review report, Tier 2 attribution)._
