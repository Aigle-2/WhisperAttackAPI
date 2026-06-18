# ADR-0004: Structured vocabulary format + LRU governance (Axis A)

**Status:** Accepted
**Date:** 2026-06-18
**Deciders:** Project owner (Aigle_2)

## Context

The reconciliation vocabularies — `fuzzy_words.txt`, `word_mappings.txt`, future
aliases — are flat text with **no size bound**. Growth is not just a performance
question: an over-grown fuzzy list **degrades precision** (more candidates above
the score cutoff → a correctly transcribed word gets "corrected" to a wrong
neighbour), and an unbounded mapping list risks cascades and cycles.

Keyterms are already budgeted (`KeytermBudget` / `apply_keyterm_budget` in
`stt_backends/keyterms.py`) but carry **no usage/recency signal**, so there is no
basis for trimming the *least useful* entries.

## Decision

Move vocabularies to **structured entries** and govern them by **recency**:

1. **Split source from usage.**
   - *Source* (versioned, human/UI-editable): **JSONL**, one record per line, with
     a stable `id` and an `origin` of `default` (curated) or `learned`.
   - *Usage* (mutable, never in git): a **sidecar** in `%LOCALAPPDATA%\VAIVOX`
     keyed by `id`, holding `last_used` and `hits`.
2. **Cap each file at N entries** (configurable, reusing the `KeytermBudget`
   pattern) and evict the **least-recently-used** entries when over cap.
3. **Protect `default` entries** from eviction; only `learned` entries are evicted.
   Apply a **grace window** so brand-new entries are never evicted before use.
4. The **"used" stamp is emitted by the reconciliation pipeline** — the *same*
   signal that feeds telemetry (ADR-0006). One instrumentation point, two uses.
5. Provide a **one-shot migration** from the legacy `.txt` files (seeding
   `last_used = now` so nothing is evicted immediately).

v1 uses plain LRU; a recency×frequency score is a possible later refinement.

## Attribution: which entries earn the usage credit

On a matched utterance, only the entries that **contributed** to the match are
credited (`last_used` / `hits`) — not every entry that merely fired. "Contributed"
means *but-for*: had the edit not happened, the match would have broken. Two tiers:

- **Tier 1 (default):** token provenance. Each pipeline step carries a
  `token → edit_ids` map; an edit is credited iff one of its output tokens survives
  into the final matched text. Deterministic, single pass, no oracle.
- **Tier 2 (on demand, ambiguous cases only):** counterfactual replay — re-run the
  pipeline without the edit and test against the **phrase index** (the Axis B index,
  reused as oracle); credit iff removal breaks the match. Guard the
  over-determination case by also testing joint removal of a redundant group.

Shapley-style fractional credit is explicitly out of scope (2^k replays). A
counterfactual on a *not-found* additionally flags **harmful edits** (one whose
removal would have produced a match) for the review report.

## Options Considered

### Option A: JSONL source + usage sidecar (chosen)
**Pros:** source stays diff-friendly, git-trackable and hand/UI-editable; hot
usage writes never touch curated content; clean join on `id`.
**Cons:** two artifacts to keep in sync; a migration step.

### Option B: Single SQLite store for everything
**Pros:** natural for frequent timestamp updates and LRU queries.
**Cons:** binary, not hand-editable, not diff-friendly — bad fit for *curated*
source vocabulary that should live in the repo.

### Option C: Keep `.txt`, add only a size cap
**Cons:** no recency signal → eviction is blind; doesn't address precision decay.

## Trade-off Analysis

The data has two natures — curated source (rarely changed, human-owned, versioned)
and usage telemetry (machine-written, hot, local). Option A respects that split;
Option B collapses it and loses git/editability; Option C can't choose *what* to
drop. This model also generalizes to the Axis B phrase index and to keyterm
ranking.

## Consequences

- Easier: bounded, self-cleaning vocabularies; precision protected; a data-driven
  basis for trimming.
- Harder: a migration path, a UI write-path update (the "add mapping" modal), and a
  stable `id` scheme.
- Enables the feedback loop (ADR-0006) to *propose* additions while governance
  keeps the files from self-poisoning.

## Action Items

1. [ ] Define the JSONL record schema + `id` rules per vocabulary type.
2. [ ] Implement `VocabularyRepository` (port) + JSONL/sidecar adapter.
3. [ ] Implement `VocabularyGovernor` (domain service): caps, grace, LRU.
4. [ ] One-shot `.txt → JSONL` migration on startup.
