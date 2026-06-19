# ADR-0011: Conservative whole-utterance phrase snap (Axis B)

**Status:** Proposed
**Date:** 2026-06-18
**Deciders:** Project owner (Aigle_2)

## Context

Reconciliation today cleans a transcript token-by-token (normalize → word mappings →
numbers → spelled codes) and fuzzy-corrects individual callsigns/phonetics, then sends
the result to VoiceAttack. VoiceAttack's `Command.Exists` is effectively an exact match,
so an utterance that is *close to* a valid VAICOM command but not exact still fails —
e.g. a leading filler word (`"uh Springfield request startup"`), a word split
(`"request start up"` vs `"request startup"`), or a misheard callsign that sits just
below the per-token fuzzy threshold (`"texako"` vs `"Texaco"`). The per-token step
cannot fix these because the mismatch is at the **whole-utterance** level.

The offline eval (ADR-0008) quantifies this: the current baseline is 12 items, 9 match,
**3 not-found — and all 3 are "near-miss recoverable"** (the expected command is in the
near-miss top-N). So the misses are structural and recoverable, not noise. ADR-0006
already sketched the snap/abstain bands and noted "the ADR for snap to follow"; the eval
already reserves an `abstain` metric for it.

The decisive constraint is the eval's `wrong_match == 0` guard: in a combat sim, firing
the **wrong** command is far worse than missing one the user simply repeats.

## Decision

Add a **conservative whole-utterance `PhraseSnapper`** as a pure domain service
(`domain/reconciliation/snapper.py`) that runs **after** per-token reconciliation. It
scores the candidate command against a **phrase index** of valid VAICOM command phrases
(`rapidfuzz`) and snaps to the best match **only when confidence is high**; otherwise it
abstains (sends the reconciled text unchanged) and emits a near-miss.

ADR-0012 extends this policy from "snap to a command phrase" to "resolve to a command
surface". Static VoiceAttack fallback still uses `PhraseSnapper`, while typed routing
uses the same conservative high/low/margin thresholds in `CommandSurfaceResolver`.

- **Three bands (one scorer, ADR-0006):**
  `score ≥ HIGH` **and** `(best − runner_up) ≥ MARGIN` → **snap** to the best phrase;
  `LOW ≤ score < HIGH` → **abstain** + record a near-miss (top-N + scores);
  `score < LOW` → send the reconciled text raw.
  The runner-up **margin** is essential: never snap when two phrases are similarly close
  (ambiguity is exactly where a wrong snap fires the wrong command).
- **Recipient-segmented phrase index.** VAICOM commands are `(recipient, command)`
  (e.g. `Texaco | request rejoin`); segmenting makes scoring robust and lets the snapper
  match the command part even when the recipient is messy. The index is produced by the
  **same generation path** as the VAICOM keyterms (ADR-0005), written to the per-user
  data dir, and **frozen** for eval reproducibility (ADR-0009 must not hot-swap it into
  tests).
- **Same scorer as near-miss.** Snapping and near-miss reporting are one function at
  different cut-offs (ADR-0006): near-miss is just the abstain-band output. No duplicate
  scoring logic.
- **Wiring.** `StopAndReconcile` now resolves command surfaces after `reconcile(...)`.
  When no typed surface is safe to dispatch, it falls back to the snapper before sending
  a static `VoiceAttackCommand`. The snap decision (snapped / abstained / raw +
  candidate + scores) is recorded in the `ReconciliationOutcome` telemetry (ADR-0006),
  and the eval's `abstain` metric starts being populated.
- **Calibration, not guesswork.** `HIGH` / `LOW` / `MARGIN` are tuned against the eval
  (ADR-0008) and real telemetry (ADR-0006) — start strict, loosen only with evidence,
  and the eval gate keeps `wrong_match == 0` as they move.

## Options Considered

### Option A: Conservative snap with abstain + runner-up margin (chosen)
| Dimension | Assessment |
|-----------|------------|
| Wrong-match risk | Minimized (margin + high cut-off + abstain) |
| Recovers near-misses | Yes, the high-confidence ones |
| Cost | A phrase index + threshold calibration |

**Pros:** recovers the recoverable misses the eval shows, while protecting the
`wrong_match == 0` bar; reuses the near-miss scorer.
**Cons:** leaves the low-confidence misses unrecovered (by design) until thresholds are
calibrated down with evidence.

### Option B: Aggressive snap (always snap to the nearest phrase)
**Pros:** maximizes raw match rate.
**Cons:** maximizes **wrong-match** — fires the wrong DCS command on ambiguous or
genuinely-unknown utterances. Violates the safety bar. Rejected.

### Option C: No snap — only grow keyterms / word mappings
**Pros:** no new component.
**Cons:** can't fix utterance-level structure (filler, word splits, recipient+command
run together) and grows the vocabulary unboundedly. Rejected.

## Trade-off Analysis

Option A trades some immediately-recoverable matches (those it abstains on) for a
near-zero wrong-match rate. Given the asymmetric cost in a combat sim (a wrong command
vs. a repeated one), conservative is correct. The eval + telemetry make threshold
loosening a measured, reversible step rather than a guess — the weakness of A (too many
abstains early) is observable and fixable, whereas B's weakness (wrong commands) is the
unacceptable one.

## Consequences

- Easier: closes the "near-miss recoverable" gap the eval quantifies; the abstain +
  near-miss stream feeds the offline review (ADR-0006) and vocabulary governance
  (ADR-0004, recency of useful entries).
- Harder: requires the phrase index (generation, ADR-0005) and threshold calibration;
  the eval must run against a **frozen** index (ADR-0009) so `wrong_match == 0` stays
  meaningful as thresholds change.
- The snapper is a pure domain service (no I/O) — unit-testable with a fixture phrase
  index, and exercised end-to-end by the ADR-0008 eval.

## Action Items

1. [~] Generate the phrase index alongside the VAICOM keyterms (reuse the ADR-0005
   generation path; write to the per-user data dir; frozen for eval). *Done as a
   whole-phrase index; **recipient segmentation** is still deferred.*
2. [x] Implement the `PhraseSnapper` domain service (snap / abstain / near-miss; runner-up
   margin; one scorer shared with near-miss) — `domain/reconciliation/snapper.py`.
3. [x] Wire it into `StopAndReconcile` as the static VoiceAttack fallback; record the
   snap decision in the `ReconciliationOutcome` (ADR-0006).
4. [x] Add eval items + tags for snap cases; keep the `wrong_match == 0` gate; calibrate
   `HIGH` / `LOW` / `MARGIN` against the eval and telemetry.
5. [x] Expose the thresholds in settings with documented, conservative defaults
   (`snap_high` / `snap_low` / `snap_margin`; injected via the snapper builder so a
   hot-reload, ADR-0009, keeps the calibration).
