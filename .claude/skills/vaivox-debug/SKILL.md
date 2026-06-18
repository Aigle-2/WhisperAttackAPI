---
name: vaivox-debug
description: >-
  Debug VAIVOX speech-to-command reconciliation through its localhost introspection
  API (ADR-0010). Use when investigating why an utterance did not fire the expected
  DCS command, inspecting effective config / loaded vocabulary / recent reconciliation
  events / live match metrics, or reproducing a reconciliation without a mic or
  VoiceAttack. Triggers: "why did command X not fire", "VAIVOX dry-run", "check the
  reconciliation metrics", "what vocabulary is loaded".
---

# VAIVOX runtime debug

VAIVOX exposes a **read-only localhost HTTP/JSON introspection API** over its query use
cases (ADR-0010). It lets you inspect runtime state and reproduce a reconciliation
**without a mic and without VoiceAttack**. The transport is the Python standard library
(`http.server`) — no extra dependency.

The API is **off by default**, binds **127.0.0.1 only**, never mutates state, never
returns secrets (config is served through the redacted accessor), and supports an
**optional bearer token**.

## 1. Enable the API

The API is gated by config in the per-user `settings.cfg` (the %LOCALAPPDATA% VAIVOX
directory). Add:

```ini
api_enabled = true
# optional overrides (defaults shown):
api_host = 127.0.0.1
api_port = 8765
# optional shared secret; when set, every request needs the bearer header:
api_token = your-token-here
```

Restart VAIVOX. On startup the composition root wires the API only when
`api_enabled` is truthy; the log line `Introspection API listening on http://...`
confirms the bound host/port.

When `api_token` is set, send `Authorization: Bearer your-token-here` on every request;
without it the server returns `401`.

## 2. Endpoints

All responses are JSON. `GET` everywhere except the dry-run `POST`.

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/healthz` | `{"status": "ok"}` (liveness; no auth payload) |
| `GET` | `/status` | version, recording flag, STT backend, **redacted** effective config |
| `GET` | `/metrics` | live match / wrong-match / not-found / unknown / abstain counts + rates |
| `GET` | `/reconciliations?limit=N` | the last `N` recorded events, oldest first (default 20, max 500) |
| `GET` | `/vocabulary` | loaded vocabulary entries + usage stats, grouped by kind |
| `POST` | `/reconcile/dry-run` | run `{"text": "..."}` through the full pipeline |

### `GET /metrics`

Aggregated from the telemetry log. Bands mirror the offline eval (ADR-0008) but are
computed from real recorded outcomes:

- `match` / `wrong_match` / `not_found` come from VoiceAttack's downstream match
  outcome — **available only once the C# plugin return channel lands (ADR-0006)**.
- `unknown` counts events whose match outcome was never reported (the current default
  until that return channel exists, so expect `unknown` to dominate today).
- `abstain` counts events the phrase snapper held back (ADR-0011); independent of the
  match band, so an event can be both `abstain` and `unknown`.

```bash
curl -s http://127.0.0.1:8765/metrics
# {"total": 42, "match": 0, "wrong_match": 0, "not_found": 0, "unknown": 41,
#  "abstain": 1, "match_rate": 0.0, "wrong_match_rate": 0.0,
#  "not_found_rate": 0.0, "abstain_rate": 0.0238}
```

### `GET /reconciliations?limit=N`

The recent provenance trail (raw -> cleaned -> command -> sent, plus match + snap):

```bash
curl -s "http://127.0.0.1:8765/reconciliations?limit=5"
# {"limit": 5, "count": 5, "events": [ {raw_text, cleaned_text, command_text,
#   sent_text, destination, match, snap}, ... ]}  # oldest first
```

`limit` is clamped to `[1, 500]`; a non-integer or non-positive `limit` is `400`.

### `GET /vocabulary`

```bash
curl -s http://127.0.0.1:8765/vocabulary
# {"total": 312, "by_kind": {"fuzzy_word": [ {id, kind, term, aliases, origin,
#   hits, last_used}, ... ], "word_mapping": [...], "alias": [...]}}
```

Every kind is present (empty list when none loaded); entries are ordered
most-recently-used first.

## 3. The killer move — reproduce a failure with `POST /reconcile/dry-run`

This is the highest-leverage endpoint. It runs text through the **full reconciliation
pipeline** (deterministic cleanup -> fuzzy correction) and returns every staged
transformation — no mic, no VoiceAttack, stateless.

```bash
curl -s -X POST http://127.0.0.1:8765/reconcile/dry-run \
  -H "Content-Type: application/json" \
  -d '{"text": "kobuletti tower"}'
# {"raw_text": "kobuletti tower", "cleaned_text": "...", "command_text": "Kobuleti tower", ...}
```

A missing/non-string `text` is `400`.

### Debug recipe: "why did command X not fire?"

1. `POST /reconcile/dry-run` with the **exact transcript** you spoke (or its closest
   guess). Read `command_text` — is it what you expected the pipeline to produce?
   - If `command_text` is wrong, the gap is in vocabulary / fuzzy correction. Check
     `GET /vocabulary` for the missing fuzzy word or word mapping.
   - If `command_text` looks right but the command still did not fire, the gap is
     downstream (VoiceAttack profile / phrase snap), not reconciliation.
2. `GET /reconciliations?limit=20` to see what actually happened on the live utterance
   (`raw_text` shows what the STT heard — often the real culprit), and what the snapper
   decided (`snap`).
3. `GET /metrics` to see whether this is a one-off or a pattern (a rising `abstain`
   suggests near-misses the snapper is conservatively declining).
4. `GET /status` to confirm the effective STT backend and config.

## Deferred / next steps

- **MCP server adapter (fast-follow, ADR-0010 item 3).** A thin MCP adapter would give
  Claude Code / Codex *native* tool access over the **same** query use cases. It is
  deliberately **not** built yet: it needs the `mcp` dependency, which is not in the
  gate environment, so adding it now would break the depless gates / package smoke test.
  When added it must reuse `application/queries.py` (no domain bypass) and stay
  read-only by the same invariants.
- **Mutating / action endpoints (ADR-0010 item 4).** Reload vocabulary, trigger
  keyterm/phrase-index generation, simulate an utterance — to be gated behind an
  explicit debug/agent mode, never destructive by default. This increment is
  **read-only**; those are the next step.
