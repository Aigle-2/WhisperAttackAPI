# ADR-0010: Runtime introspection API for agentic tooling (+ agent skills)

**Status:** Accepted
**Date:** 2026-06-18
**Deciders:** Project owner (Aigle_2)

## Context

This is a large rewrite, and the hardest thing to debug — *why did command X not
fire?* — is slow if it means reading logs or launching DCS. The owner wants agentic
systems (Claude Code, Codex) to **access runtime state** (effective config, loaded
vocabulary, recent reconciliations, in-memory variables) for fast debug/monitoring,
plus **agent-facing skills/prompts** that document that access. The hexagonal design
already exposes query use cases; an API is just another driver adapter over them.

## Decision

Expose a **read-mostly runtime introspection API** as a driver adapter over
application **query use cases**, with agent-facing documentation.

- **Transport:** a **localhost HTTP/JSON API (FastAPI)** as the core. Its
  **auto-generated OpenAPI schema doubles as the machine-readable contract** agents
  consume — so most of the "write a prompt describing the API" work is free. A thin
  **MCP server adapter** (fast-follow) gives Claude Code / Codex *native* tool access
  over the **same** use cases.
- **Read surface:** status / version / `ProductIdentity`; effective **redacted**
  config; loaded keyterm/vocab context + per-source sizes; recording state; **recent
  reconciliation events** (raw → cleaned → fuzzy → snap → sent → outcome);
  near-miss log; vocabulary entries + usage stats (`last_used`/`hits`); live metrics;
  recent log tail; last error.
- **Killer debug affordance:** `POST /reconcile/dry-run { text }` runs text through
  the **full pipeline** (incl. attribution + nearest-phrase) and returns every
  transformation plus *would-it-match*, **with no mic and no VoiceAttack**. An agent
  reproduces and diagnoses a failure in one call.
- **Actions (mutating):** reload vocabulary, trigger generation, simulate an
  utterance — **gated behind an explicit debug/agent mode**, never destructive by
  default.
- **Agent docs:** a Claude Code **skill** (`SKILL.md`) + MCP tool descriptions + an
  `AGENTS.md`/prompt snippet with debug recipes; the OpenAPI spec is canonical.

## Layering

Query use cases live in `application/`; the **HTTP** and **MCP** servers are
`infrastructure/api/` driver adapters that go *through* the use cases (no domain
bypass — same dependency rule). They reuse the same ports as the app and the eval
harness (ADR-0008): `VocabularyRepository`, `TelemetrySink`/store, `ConfigProvider`,
`PhraseSnapper`.

## Options Considered

### Option A: read-mostly HTTP (OpenAPI) + MCP adapter, gated actions (chosen)
**Pros:** universal (HTTP/curl/any agent) **and** native agent tooling (MCP) over one
set of use cases; OpenAPI removes most prompt-writing.
**Cons:** two thin adapters to maintain.

### Option B: MCP only
**Pros:** native for Claude Code/Codex.
**Cons:** not universal; harder to curl/test; no free OpenAPI contract.

### Option C: HTTP only
**Pros:** universal.
**Cons:** no native tool integration for agents.

### Option D: none (logs only — status quo)
**Cons:** slow agentic debug; defeats the stated goal.

## Trade-off Analysis

Option A delivers both universality and native agent integration from a single set of
use cases, at the cost of two thin adapters. The dry-run endpoint is the highest-
leverage piece: it collapses a multi-step, DCS-in-the-loop debug into one stateless
call.

## Consequences

- Easier: agents (and humans) inspect and reproduce runtime behavior fast; the eval
  and the API share query use cases.
- Harder: a localhost server is new attack surface → it ships **off by default**,
  **binds 127.0.0.1 only**, supports an optional bearer token, is **read-only by
  default** with actions opt-in, and never returns secrets (reuse the redacted config
  accessor). Agent docs must be kept in sync with the API.
- `ProductIdentity` (ADR-0002) gains a dedicated, off-by-default API port.

## Action Items

1. [ ] Define query use cases (status, config, vocab, reconciliations, metrics, dry-run).
2. [ ] HTTP/JSON adapter (FastAPI) + auto OpenAPI; localhost + opt-in + optional token.
3. [ ] MCP server adapter over the same use cases.
4. [ ] Gate mutating actions behind debug/agent mode.
5. [ ] Author the Claude Code skill + MCP tool docs + `AGENTS.md` debug recipes.
