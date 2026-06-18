# Architecture Decision Records

This directory records the load-bearing decisions for the **VAIVOX** rewrite
(a divergence of WhisperAttackAPI, itself a fork of WhisperAttack / KneeboardWhisper).

VAIVOX sits on top of **VoiceAttack 2** and **VAICOM Community** and turns
push-to-talk speech into DCS radio commands. The rewrite exists to replace an
legacy architecture with a maintainable, testable, modular one *before*
new reconciliation features are built on top of it.

## Conventions

- One decision per file: `NNNN-kebab-title.md`.
- Status lifecycle: `Proposed → Accepted → Deprecated → Superseded`.
- A decision is changed by adding a *new* ADR that supersedes the old one, not by
  editing history.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-hexagonal-architecture-without-heavy-ddd.md) | Hexagonal architecture + SOLID, without heavy DDD | Accepted |
| [0002](0002-clean-separation-product-identity.md) | Clean separation from upstream via one ProductIdentity | Accepted |
| [0003](0003-rebrand-to-vaivox.md) | Rebrand to VAIVOX | Accepted |
| [0004](0004-vocabulary-structured-format-and-governance.md) | Structured vocabulary format + LRU governance (Axis A) | Accepted |
| [0005](0005-no-redistribution-of-vaicom-derived-data.md) | No redistribution of VAICOM-derived data; transparent local generation | Accepted |
| [0006](0006-telemetry-via-plugin-return-channel.md) | Telemetry via the plugin return channel (Axis C) | Accepted |
| [0007](0007-tooling-build-and-ci-standard.md) | Tooling, build & CI standard | Accepted |
| [0008](0008-test-and-evaluation-strategy.md) | Test & evaluation strategy (LLM dataset + VAICOM mock) | Accepted |
| [0009](0009-vocabulary-reload-model.md) | Vocabulary / index reload model (hot-apply vs restart) | Accepted |
| [0010](0010-runtime-introspection-api-for-agents.md) | Runtime introspection API for agentic tooling (+ skills) | Accepted |
| [0011](0011-conservative-phrase-snap.md) | Conservative whole-utterance phrase snap (Axis B) | Proposed |

The roadmap that consumes these decisions is in [../MIGRATION_PLAN.md](../MIGRATION_PLAN.md).
