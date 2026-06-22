# VAIVOX — remaining tasks

A living punch-list of what's left after Phases 0–5 (core). The phased narrative lives in
[`docs/MIGRATION_PLAN.md`](docs/MIGRATION_PLAN.md); decisions are in [`docs/adr/`](docs/adr/).
At last update the tree is green: **336 tests**, ruff / format / mypy / import-linter all
pass via `uv run` (see [AGENTS.md](AGENTS.md)).

**Done so far (Phase 5):** A governance core (ADR-0004), C telemetry persistence
(ADR-0006 §1), the eval harness (ADR-0008), B phrase-snap (ADR-0011), the VAICOM
keyterm + phrase-index generator with auto-discovery + **background generation on first
run / on stale** (ADR-0005), the **idle-gated phrase-index hot-reload** (ADR-0009), and the
introspection API — read endpoints + **gated mutating actions** + the **MCP server
adapter** (`vaivox-mcp`) + `vaivox-debug` skill (ADR-0010).

---

## 1. Blocked — needs a Windows + VoiceAttack + DCS machine (not CI-testable)

These gate the match-signal-dependent work; everything buildable without them is done.

- [x] **C# plugin return channel (ADR-0006).** Implemented end-to-end (M1–M6, see
  [`docs/RETURN_CHANNEL_PLAN.md`](docs/RETURN_CHANNEL_PLAN.md)): frozen wire protocol +
  shared golden vectors, `plugin/VaivoxVAPlugin/VaivoxVAPlugin.cs` replies
  `{ v, matched, resolved_command }` on the same socket, and
  `infrastructure/voiceattack/sink.py` reads it best-effort into `ReconciliationOutcome.match`.
  **Off by default** (`voiceattack_await_result = false`); remaining = deploy the rebuilt
  plugin + flip the flag + the real-install E2E ([runbook](docs/RETURN_CHANNEL_E2E_RUNBOOK.md), AC5).
- [x] **Live usage stamping / recency (ADR-0004).** The `UsageStamper`
  (`application/usage_stamping.py`) runs Tier 1 attribution
  (`VocabularyGovernor.attribute_tier1` over `sent_text.split()` vs `{id: tokens(term+aliases)}`)
  and calls `VocabularyRepository.mark_used(credited, now)` on the VoiceAttack path of the
  shared `route_command` — now **conditioned on `matched == True`** (a *sent-but-unmatched*
  command no longer credits vocabulary; `None`/unknown credits nothing). Kneeboard never
  stamped; best-effort so a failed write never breaks dispatch. *Inert in production until
  the channel is enabled* (above). Tier 2 below.
- [x] **Near-miss capture (ADR-0006 §3).** `application/learn_from_outcome.py`
  (`LearnFromOutcome`) + the pure `domain/vocabulary/learning.py`: on a confirmed not-match
  or a snap abstain, it proposes a mapping from the nearest valid phrases and, per the
  `vocab_auto_learn` policy (default off / human-in-the-loop), writes a `LEARNED` entry.
- [ ] **Tier 2 counterfactual attribution (ADR-0004).** Pipeline-replay + phrase-index
  oracle on ambiguous matches. Larger; refines Tier 1 now that the match signal exists.
- [x] **C# `dotnet` build + bundled `.vap` (ADR-0002/M4/M6).** `plugin/VaivoxVAPlugin.csproj`
  + `.sln` are committed (net48, no VoiceAttack reference needed — `dynamic`); `build_exe.ps1`
  bundles the built DLL + `.vap` under `Apps/VAIVOX/` in the release. *Manual remainder:*
  re-point the `.vap` commands to the new plugin GUID inside VoiceAttack on the target install
  (one-time). The C# unit tests run in the CI `dotnet` job (Windows), unverified until its first run.
- [ ] **Generator end-to-end (ADR-0005).** Run `python tools/generate_vaicom_keyterms.py`
  against a real VAICOM install; verify the emitted `%LOCALAPPDATA%\VAIVOX\vaicom_keyterms.txt`
  + `phrase_index.txt` shape (the phrase index must line up with VoiceAttack's actual
  command strings) and that the snapper improves matches with `wrong_match == 0` held.
- [ ] **Phase 3/4 runtime validation.** The GUI window/tray, the real socket/audio/keyboard
  adapters, the PyInstaller build (`build_exe.ps1`), and the uv-based CI were verified *by
  construction* but never executed. Smoke-test a real run + a built exe.

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
  `PhraseSnapper`, so nothing leaks into the metrics. *Remaining:* the LRU maintenance pass
  and the optional JSONL file-watch (ADR-0009 action item 3). The pipeline now reads
  word-mappings/fuzzy from the repository (via `VocabularyProvider`, read live each utterance
  with a sub-second cache), so a hot vocab swap is the cache TTL, not a dedicated `IdleGatedSwap`.
- [~] **Governance maintenance wiring (ADR-0004).** *Wired but inert by default.* The
  `UsageStamper` runs the LRU pass (`VocabularyGovernor.govern` + `replace_entries`) per
  kind after stamping, gated on a configured cap: `composition.build_usage_stamper` builds
  per-kind `EvictionPolicy` only when `vocab_max_entries` (+ optional `vocab_grace_days`) is
  set in `settings.cfg`; with no cap (the default) nothing is evicted, and `DEFAULT` seeds
  are protected regardless — so eviction can only ever touch `LEARNED` entries. *De facto
  inert until `LEARNED` entries exist* (near-miss capture is return-channel-gated above);
  the scaffolding activates automatically once they do.
- [x] **`.txt → JSONL` vocab migration (ADR-0004 action item).** `migrate_legacy_vocabulary`
  + the pure `legacy_to_entries` (`infrastructure/vocabulary/migration.py`) convert the
  merged `fuzzy_words.txt` / `word_mappings.txt` into structured `VocabularyEntry` records
  (aliases grouped by replacement, slug ids, `DEFAULT` origin) and seed them through the
  repository; one-shot CLI `tools/migrate_vocabulary.py`, idempotent by id. Tested (converter
  + a real repo round-trip) and validated end-to-end on the repo defaults (21 fuzzy + 48
  mappings). *Follow-up done:* the same migration now **auto-seeds** on first launch from
  `composition.build_vocabulary_repository` (gated on the JSONL source being absent), and the
  pipeline reads vocab from the repository via the `VocabularyProvider` projection — see
  "Vocabulary source unification" below.
- [x] **Vocabulary source unification (ADR-0004).** The reconciliation pipeline and the
  introspection `GET /vocabulary` now read from **one** store — the JSONL repository. New
  `application.ports.VocabularyProvider` port (the two flat reads); production adapter
  `infrastructure/vocabulary/repository_provider.py` `RepositoryVocabularyProvider` projects
  the structured entries back to `word_mappings` / `fuzzy_words` (inverse of the migration),
  read live each utterance behind a sub-second TTL cache. `StopAndReconcile`,
  `DryRunReconcile`, and `SimulateUtterance` take the provider (the vocab methods left
  `ConfigProvider`). The UI "Add word mapping" writes through the `AddWordMapping` use case
  (`application/add_vocabulary.py`) into the repository; `build_vocabulary_repository`
  auto-seeds on first launch. Tested: provider projection + TTL + liveness, `AddWordMapping`
  add/merge/no-op, and the composition seed + parity-with-flat-files.
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

_Update this file as items land (and prefer adding a new ADR over editing decisions). When
the C# return channel ships, revisit section 1 — most of it unblocks at once._
