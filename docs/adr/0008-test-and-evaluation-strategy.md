# ADR-0008: Test & evaluation strategy (LLM dataset + VAICOM mock)

**Status:** Accepted
**Date:** 2026-06-18
**Deciders:** Project owner (Aigle_2)

## Context

We need to **quantify** the architecture, not just trust it: reconciliation quality
(how often transcribed speech resolves to the right VAICOM command) must be
*measurable* and *regression-gated*. Manual testing inside DCS is slow,
non-reproducible, and can't produce a number. The hexagonal design (ADR-0001) makes
the domain runnable with no I/O, which is exactly what an automated evaluation
needs.

## Decision

Adopt a test pyramid mapped onto the layers, topped by an **offline reconciliation
eval** driven by an **LLM-generated dataset** and a **mocked VAICOM**.

| Level | Scope | Notes |
|-------|-------|-------|
| **Unit** | domain: pipeline, normalization, fuzzy, snapper, governor, attribution | pure, fast, no I/O — the bulk of tests |
| **Contract** | every STT adapter vs the `SpeechToTextProvider` port; `CommandSink` vs the VAICOM mock | pins LSP compliance |
| **Integration** | adapters with real sockets/files via fakes | |
| **Architecture** | `import-linter` dependency-rule contracts | ADR-0007 |
| **Reconciliation eval** | full pipeline → mocked VAICOM, over the dataset → **metrics** | the "quantify" layer |

**LLM-generated dataset.** An LLM produces realistic STT *outputs* for DCS/VAICOM
commands, seeded from the real command grammar (the Axis B phrase index, so
expectations are valid). Each item: `{ raw_stt, expected_command, tags }`, where
`tags` mark the failure mode being probed: filler words, number form (`"two"` vs
`2`), spelled codes (`U L M B`), misheard callsigns, accented-English artifacts,
recipient+command said without a pause, etc. Stored as a **versioned JSONL fixture**.
Keep a small **human-curated golden set** alongside the larger LLM-augmented set.

**VAICOM mock.** A test double implementing the `CommandSink` / match oracle over a
known command set (a fixture phrase index). It returns `matched` / `not_found`
exactly like the real plugin's `Command.Exists`, so the whole reconciliation path is
exercised **without VoiceAttack, DCS, or VAICOM running**. The same mock is the
oracle for Tier 2 attribution tests (ADR-0004).

**Metrics & gate.** The eval reports **match rate, wrong-match rate, abstain rate,
and near-miss quality** (overall and per `tag`). CI asserts no regression below a
committed baseline.

## Options Considered

### Option A: LLM dataset + VAICOM mock + metrics (chosen)
**Pros:** reproducible, quantified, CI-gated; exercises the real pipeline; cheap to
expand coverage by generating more tagged items.
**Cons:** synthetic STT noise only approximates real transcribers; risk of
overfitting the vocabulary to the synthetic set.

### Option B: Manual DCS testing only
**Cons:** not reproducible, produces no metric, cannot gate regressions.

### Option C: Real recorded-audio corpus end to end
**Pros:** ground truth.
**Cons:** expensive and slow to build/maintain. Kept only as a small complement.

## Trade-off Analysis

Option A is the only one that yields a *number* on every CI run. Its weakness
(synthetic ≠ real audio) is mitigated by keeping a small real-audio/real-VAICOM
**smoke test** (a slice of Option C) as a ground-truth anchor, and by tagging items
so metrics stay diagnostic rather than a single opaque score.

## Consequences

- Easier: regressions in reconciliation are caught automatically and attributed to a
  failure-mode tag; the architecture is demonstrably exercised end to end.
- Harder: maintain the dataset generator + fixtures; periodically refresh against a
  small real-audio anchor to avoid synthetic drift.
- The eval runs against a **frozen vocab/index snapshot** for reproducibility — which
  is why runtime hot-reload (ADR-0009) must never leak into tests.

## Action Items

1. [ ] Define the dataset JSONL schema (`raw_stt`, `expected_command`, `tags`).
2. [ ] Build the LLM dataset generator seeded from the phrase index.
3. [ ] Implement the VAICOM mock (`CommandSink` + match oracle over a fixture index).
4. [ ] Build the eval runner + metrics; commit a baseline; gate CI.
5. [ ] Add a small human-curated golden set + a real-audio smoke anchor.
