# VAIVOX — remaining tasks

A living punch-list of what's left after Phases 0–5 (core). The phased narrative lives in
[`docs/MIGRATION_PLAN.md`](docs/MIGRATION_PLAN.md); decisions are in [`docs/adr/`](docs/adr/).
At last update the tree is green: **203 tests**, ruff / format / mypy / import-linter all
pass via `uv run` (see [AGENTS.md](AGENTS.md)).

**Done so far (Phase 5):** A governance core (ADR-0004), C telemetry persistence
(ADR-0006 §1), the eval harness (ADR-0008), B phrase-snap (ADR-0011), the VAICOM
keyterm + phrase-index generator with auto-discovery (ADR-0005), and the read-only
introspection API + `vaivox-debug` skill (ADR-0010).

---

## 1. Blocked — needs a Windows + VoiceAttack + DCS machine (not CI-testable)

These gate the match-signal-dependent work; everything buildable without them is done.

- [ ] **C# plugin return channel (ADR-0006).** After `Command.Exists`, have
  `plugin/VaivoxVAPlugin/VaivoxVAPlugin.cs` report `{ text, matched, resolved_command }`
  back on the same socket; read it in `infrastructure/voiceattack/` and populate
  `ReconciliationOutcome.match`. **This is the key unblocker** for the three items below.
- [ ] **Live usage stamping / recency (ADR-0004).** On a matched outcome, run Tier 1
  attribution and call `VocabularyRepository.mark_used(credited_ids, now)` from
  `StopAndReconcile`. Seam is in place (`attribute_tier1` → `credited_ids` → `mark_used`);
  it just needs the `matched` signal above.
- [ ] **Near-miss capture (ADR-0006 §3).** When the snap abstains / no match, record the
  top-N nearest phrases. The snapper already emits near-misses into telemetry; this is the
  match-signal-gated review/report side.
- [ ] **Tier 2 counterfactual attribution (ADR-0004).** Pipeline-replay + phrase-index
  oracle on ambiguous matches. Larger; needs the match signal.
- [ ] **C# `dotnet` build + bundled `.vap` re-point (ADR-0002).** Build the plugin DLL
  (no `.csproj` is committed — it depends on the local VoiceAttack SDK path) and re-point
  the commands in `VAIVOX - VA Profile.vap` to the new plugin GUID inside VoiceAttack.
- [ ] **Generator end-to-end (ADR-0005).** Run `python tools/generate_vaicom_keyterms.py`
  against a real VAICOM install; verify the emitted `%LOCALAPPDATA%\VAIVOX\vaicom_keyterms.txt`
  + `phrase_index.txt` shape (the phrase index must line up with VoiceAttack's actual
  command strings) and that the snapper improves matches with `wrong_match == 0` held.
- [ ] **Phase 3/4 runtime validation.** The GUI window/tray, the real socket/audio/keyboard
  adapters, the PyInstaller build (`build_exe.ps1`), and the uv-based CI were verified *by
  construction* but never executed. Smoke-test a real run + a built exe.

## 2. Buildable in CI — no hardware required

- [ ] **MCP server adapter (ADR-0010).** A thin MCP server over the *same* query use cases
  as the HTTP API. Needs a dependency decision: add `mcp` as an optional extra and import
  it lazily (the gate env is dep-light and the smoke test imports every module). Fast-follow
  to the read API.
- [ ] **Gated mutating API actions (ADR-0010).** `reload vocabulary`, `trigger generation`,
  `simulate utterance` — behind an explicit debug/agent mode, never destructive by default.
  The API is read-only today.
- [ ] **Background generation on first run / on stale (ADR-0005).** On startup, if the
  keyterms / phrase index are missing or stale, run the generator (it already
  auto-discovers) on a background thread into the data dir. Testable with the generator
  faked; trigger logic + status only.
- [ ] **Vocabulary / index hot-reload (ADR-0009).** Idle-gated atomic swap. Today the
  phrase index + vocab are loaded once at composition (frozen per session); add a
  thread-safe swap layer. Must never leak into the eval (it runs on a frozen snapshot).
- [ ] **Governance maintenance wiring (ADR-0004).** Wire `VocabularyGovernor.govern`
  (eviction) into a maintenance pass + `VocabularyRepository.replace_entries`. Meaningful
  only once usage data exists (depends on live stamping above).
- [ ] **`.txt → JSONL` vocab migration (ADR-0004 action item).** One-shot migration of the
  legacy `fuzzy_words.txt` / `word_mappings.txt` into the structured JSONL source.
- [ ] **Phrase-snap follow-ups (ADR-0011).** Recipient-segment the phrase index + snapper
  (v1 is whole-phrase `token_sort_ratio`); expose the `HIGH` / `LOW` / `MARGIN` thresholds
  in `settings.cfg` (they live as named constants today).
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
