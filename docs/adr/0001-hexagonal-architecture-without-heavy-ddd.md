# ADR-0001: Hexagonal architecture + SOLID, without heavy DDD

**Status:** Accepted
**Date:** 2026-06-18
**Deciders:** Project owner (Aigle_2)

## Context

The codebase is a legacy fork. The functional core is sound but the structure
is not: `whisper_server.py` is a god-module mixing a socket server, audio
recording, text cleanup, fuzzy matching, the VoiceAttack sink and the kneeboard
sink in one class. There are no enforced layering rules and the domain logic
cannot be exercised without real I/O.

Forces at play:

- We want maintainability, testability and *obvious* modularity.
- The STT layer (`stt_backends/base.py` + `factory.py` + four backends) is already
  a clean port/adapter — proof the team can hold the pattern.
- This is a **single-process desktop app, one bounded context, no database, no
  transactions, solo maintainer**. Full DDD tactical machinery would be ceremony.

## Decision

Adopt **Hexagonal architecture (ports & adapters)** + the **Clean dependency
rule** (dependencies point inward: infrastructure → application → domain) + the
**SOLID** principles.

Use only the *lightweight* DDD building blocks that earn their keep here:

- **Value objects** (e.g. `Transcription`, `RecognizedCommand`, `VocabularyEntry`).
- **Domain services** (e.g. `ReconciliationPipeline`, `VocabularyGovernor`,
  `PhraseSnapper`).
- One small **Vocabulary** consistency boundary.

Explicitly **out of scope** (over-engineering for this app): aggregate ceremony,
CQRS, event sourcing, a unit-of-work/transaction abstraction, and a domain-event
bus. Telemetry "events" are plain value objects emitted through a port, not an
event-sourcing system.

## Options Considered

### Option A: Tidy the procedural code in place
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Cost | Low |
| Testability | Still I/O-bound |
| Meets goals | No |

### Option B: Hexagonal + SOLID + light DDD (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium |
| Cost | Medium (upfront restructuring) |
| Testability | Domain testable with zero I/O |
| Meets goals | Yes |

### Option C: Full Clean/DDD/CQRS
| Dimension | Assessment |
|-----------|------------|
| Complexity | High |
| Cost | High |
| Testability | High but with heavy ceremony |
| Meets goals | Over-engineered for a desktop app |

## Trade-off Analysis

Option B gives the testability and swap-ability we want without the ceremony of
Option C. The decisive constraint is Cockburn's test: *the domain must run from
tests with no UI and no infrastructure*. Option A fails it; Option C passes it but
at a maintenance cost unjustified by a single-context desktop tool.

## Consequences

- Easier: swap STT providers / output sinks; unit-test reconciliation with no
  sockets, mic, or network; enforce boundaries automatically (see ADR-0007's
  `import-linter`).
- Harder: more files and one layer of indirection; an upfront restructuring pass.
- Revisit if: a genuinely second bounded context appears (unlikely).

## Action Items

1. [ ] Define the target package tree (see MIGRATION_PLAN).
2. [ ] Extract the domain out of `whisper_server.py` behind ports.
3. [ ] Add `import-linter` contracts to encode the dependency rule.
