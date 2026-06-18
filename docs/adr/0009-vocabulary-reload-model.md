# ADR-0009: Vocabulary / index reload model (hot-apply vs restart)

**Status:** Accepted
**Date:** 2026-06-18
**Deciders:** Project owner (Aigle_2)

## Context

The feedback loop (ADR-0006) and governance (ADR-0004) run live in the background:
usage stamps are written continuously, mappings/aliases get added, the VAICOM
vocabulary/phrase index can be regenerated (ADR-0005), and LRU eviction trims the
learned pool. The open question: do these evolutions take effect **at runtime**, or
does the user have to **restart** to benefit from them?

Today the behavior is inconsistent: UI-added word mappings apply live, but
hand-edited files require a restart.

## Decision

The **`VocabularyRepository` is the single in-memory source of truth** that the
reconciliation pipeline reads per utterance. All mutations go through it with
thread-safe semantics. Changes are classified by latency tolerance:

| Class | Examples | When it takes effect |
|-------|----------|----------------------|
| **Live, immediate** | usage stamps (`last_used`/`hits`); UI-accepted mappings/aliases | next utterance, no restart |
| **Hot atomic swap at idle** | regenerated VAICOM vocab / phrase index (ADR-0005); LRU maintenance pass | swapped behind a lock **only when not recording**, never mid-utterance; the UI notifies ("vocabulary refreshed") |
| **Restart-only** | `ProductIdentity` (ports/GUID/data dir), `stt_backend` selection, credentials, the C# plugin DLL | on next launch / VA reload |

Mechanism: an atomic reference swap of the in-memory vocab/index; an optional
file-watch picks up external JSONL edits without a restart (fixing today's
inconsistency). Behavioral swaps are gated on the idle (not-recording) state and are
**observable** in the UI.

## Options Considered

### Option A: Tiered hot-apply with idle-gated atomic swap (chosen)
**Pros:** users get improvements without restarting; safe (no mid-utterance change);
fixes the hand-edit inconsistency.
**Cons:** needs thread-safety + an idle guard; introduces intra-session
non-determinism (mitigated: idle-only + observable).

### Option B: Load everything at startup only
**Pros:** fully deterministic per session; simplest.
**Cons:** every evolution needs a restart — poor UX for a tool used in long sessions.

### Option C: Fully live, swap anytime
**Cons:** a swap mid-utterance could change matching behavior unpredictably during a
command — unacceptable in DCS.

## Trade-off Analysis

Option A captures Option B's safety (no mid-command change) while delivering the live
UX the feedback loop is meant to provide. Option C's risk is real in a flight sim, so
swaps are confined to the idle state.

## Consequences

- Easier: continuous improvement is felt without restarts; consistent reload story.
- Harder: thread-safe atomic swap + idle gating; clear UI signalling of swaps.
- Tests pin a **frozen snapshot** (ADR-0008): hot-reload must never leak into the
  eval, or metrics become irreproducible.

## Action Items

1. [ ] Make `VocabularyRepository` the thread-safe in-memory source of truth.
2. [ ] Implement idle-gated atomic swap for regenerated vocab/index + LRU passes.
3. [ ] Add optional file-watch for external JSONL edits.
4. [ ] Surface "vocabulary refreshed / evicted N" in the UI.
