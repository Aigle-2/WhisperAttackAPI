# ADR-0003: Rebrand to VAIVOX

**Status:** Accepted
**Date:** 2026-06-18
**Deciders:** Project owner (Aigle_2)

## Context

The product needs a name distinct from `WhisperAttack` (upstream brand), `Whisper`
(OpenAI's model) and `Attack`. Its ecosystem is **VAICOM**, which was open-sourced
by Hollywood_315 on 31 Oct 2022 and is now maintained by the community as
`VAICOM-Community` / `VAICOMPRO-Community` on GitHub. Distribution will be **OSS via
GitHub + community forums + Discord** (no commercial domain, no PyPI).

## Decision

The product name is **VAIVOX**.

The familial echo of VAICOM is acceptable — even idiomatic — now that VAICOM is a
community OSS project rather than a commercial one; companion-project naming is a
norm in that ecosystem. We add a **courtesy line** to the README stating VAIVOX is
an independent companion, not affiliated with VAICOM Community, with a link to it.

## Options Considered

### Option A: VAIVOX (chosen)
**Pros:** instant ecosystem recognition; fits the `VAICOM…` community naming
culture; the project owner's preferred direction.
**Cons:** minor SEO collision (an unrelated crypto token and an AI service at
`vaivox.com`); `.com` is taken.

### Option B: A neutral, non-VAICOM name
**Pros:** zero brand adjacency; clean search.
**Cons:** loses the immediate "this belongs to the DCS/VAICOM voice ecosystem"
signal.

### Option C: Keep a `WhisperAttack*` name
**Cons:** collides with upstream and defeats the separation in ADR-0002.

## Trade-off Analysis

With VAICOM now community OSS, the original objection to Option A (mimicking a
*commercial* trademark) evaporates. The residual cost is only SEO pollution, which
is irrelevant for a tool distributed through GitHub/Discord/DCS forums. The
ecosystem-recognition upside outweighs it.

## Consequences

- The `.com` and PyPI availability are non-issues for this distribution model.
- A courtesy/attribution note is required in the README (see ADR-0005 for the
  related licensing posture).
- Verify the **GitHub repo/org name** and **Discord** name are free *at
  publication time*. The repo rename is deferred: development happens on a branch
  in the current repo now; a clean public repo is created at publication.

## Action Items

1. [ ] Wire `VAIVOX` through `ProductIdentity` (ADR-0002).
2. [ ] Add the README courtesy/attribution note + link to VAICOM-Community.
3. [ ] At publication: check GitHub/Discord name availability.
