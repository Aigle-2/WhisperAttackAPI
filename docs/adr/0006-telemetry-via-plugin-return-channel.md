# ADR-0006: Telemetry via the plugin return channel (Axis C)

**Status:** Accepted
**Date:** 2026-06-18
**Deciders:** Project owner (Aigle_2)

## Context

Reconciliation is fire-and-forget today: the Python server sends transcribed text
to VoiceAttack and never learns whether it matched. The match outcome already
exists — the C# plugin computes `vaProxy.Command.Exists(receivedMessage)` and
either executes or logs `"not found"`
(`VoiceAttackPlugin/WhisperAttack/WhisperAttack.cs`) — but it is **discarded**.
Without that signal, the system cannot measure reconciliation success, capture
near-misses, or stamp vocabulary usage (ADR-0004).

The owner's constraint: stay **100% in-project** (we will not modify VoiceAttack 2
or VAICOM).

## Decision

Add a **live return channel through our own C# plugin**. After the match attempt,
the plugin reports the outcome (`{ text, matched }`, plus the resolved command when
matched) back to the Python server. Python records a structured telemetry event:
`raw → cleaned → fuzzy → snapped → sent → matched`, and near-misses (top-N nearest
phrases + scores when the snap abstains or the match fails).

The plugin is **our code**, so modifying it is *not* "modifying VoiceAttack". The
same event also stamps `last_used` for vocabulary governance (ADR-0004) — one
instrumentation point serving both axes.

## Return pipeline (what happens after the outcome returns)

The channel is a **synchronous request/response on the existing connection**: the
server sends the command text to the plugin and reads the outcome back on the
*same* socket before closing — no new port, no new listener. The plugin replies as
soon as the match is decided (right after `Command.Exists`), so the round-trip does
**not** wait for the in-game radio call to finish (negligible added latency).

Once `MatchOutcome { matched, resolved_command }` is back, the `StopAndReconcile`
use case emits one `ReconciliationOutcome` carrying the full provenance
(raw → cleaned → fuzzy edits → snap candidate → sent text → which vocabulary entry
ids fired). The application layer fans it out, via ports:

1. **Telemetry (always):** `TelemetrySink.record(outcome)` appends the full chain to
   JSONL in `%LOCALAPPDATA%\VAIVOX`.
2. **Usage stamping (only when `matched`):** `VocabularyRepository.mark_used(credited_ids)`
   sets `last_used` / `hits` for the entries that **contributed** to the match
   (Tier 1 token-provenance, Tier 2 counterfactual on ambiguity — see ADR-0004), not
   every entry that merely fired. Recency means *useful*; entries that fired but
   produced a non-matching command decay toward eviction.
3. **Near-miss capture (not matched / snap abstained):** record the utterance + the
   top-N nearest valid command phrases + scores → the offline review that *proposes*
   new mappings/aliases. Nothing is auto-applied (human-in-the-loop).
4. **UI status:** the writer shows `✓ matched: <command>` or
   `✗ no match — nearest <candidate> (NN%)`.

The near-miss top-N is computed by the **same `PhraseSnapper` scorer** used for
snapping — `rapidfuzz` against the recipient-segmented phrase index — only at a
lower threshold. Snapping and near-miss reporting are therefore *one* function at
different cut-offs (Axis B ↔ C): `score ≥ high+margin → snap`, `low ≤ score < high →
abstain + near-miss`, `score < low → send raw`.

**Boundaries & robustness:**

- `matched` means VoiceAttack found and dispatched a command for that exact text —
  it is **not** a guarantee that VAICOM issued the in-game radio call (downstream,
  a different failure class, not cheaply observable).
- After ADR-0012, `MatchOutcome` is explicitly the static VoiceAttack
  `Command.Exists` result. Dynamic targets such as `VaicomF10Action` record
  `resolution` and `dispatch` telemetry instead; their `match` field remains `null`
  because no static VoiceAttack exact-name check was performed.
- The return is **best-effort**: a short read timeout; on no reply the outcome is
  `unknown`, telemetry records it, no usage stamp, and the app continues. The user
  is never blocked.

## Options Considered

### Option A: Plugin return channel (chosen)
| Dimension | Assessment |
|-----------|------------|
| In-project | Fully — our plugin, our server |
| Coupling | None to external log formats |
| Cost | Plugin rebuild/redeploy + a small wire protocol |

**Pros:** authoritative match signal at the source; no external coupling.
**Cons:** requires rebuilding/redeploying the plugin DLL.

### Option B: Offline VAICOMPRO.log correlation
| Dimension | Assessment |
|-----------|------------|
| In-project | Partially — reads VAICOM's log |
| Coupling | Tied to VAICOM's log format (external, may change) |
| Cost | No plugin change |

**Pros:** no plugin change.
**Cons:** couples us to a VAICOM artifact we do not control; less "in-project".

## Trade-off Analysis

Both avoid touching VAICOM/VA themselves. Option A keeps *everything* in code we
own and reads the match boolean exactly where it is computed; Option B trades the
plugin rebuild for a fragile dependency on VAICOM's log format. Given the
in-project constraint, Option A is the cleaner fit.

## Consequences

- Easier: closes the reconciliation loop; enables near-miss capture and
  data-driven mapping/alias suggestions; feeds ADR-0004's recency signal.
- Harder: define a minimal wire protocol for the result; plugin redeploy is now part
  of releases (already our artifact via ADR-0007's CI).

## Action Items

1. [x] Define the result message format (text, matched, resolved command). One JSON line
   `{ "text", "matched", "resolved_command" }` (newline-terminated), `resolved_command` =
   the received text when matched (exact-name check) else `null`.
2. [x] Emit the result from the plugin after the match attempt. `HandleVaivoxCommand`
   replies on the same socket right after `Command.Exists` (before `Command.Execute`);
   `VoiceAttackCommandSink.send` reads it back (short timeout; EOF/timeout/malformed →
   `None`/unknown for backward compatibility) and `route_command` records it in
   `ReconciliationOutcome.match` and stamps usage on a match. *Deploying* the rebuilt DLL +
   the DCS smoke is the only hardware-gated remainder (see `TODO.md` §1).
3. [x] Add a `TelemetrySink` port + JSONL adapter in `%LOCALAPPDATA%\VAIVOX` (Phase 5 §1:
   `JsonlTelemetrySink`, config-gated `telemetry_enabled`).
4. [ ] Build the offline review report (frequent not-founds, suggested mappings) — needs
   accumulated live match data from the deploy above.
5. [x] Add ADR-0012 typed routing telemetry fields (`resolution`, `dispatch`) while
   preserving `match` for the VoiceAttack static path only.
