# ADR-0002: Clean separation from upstream via one ProductIdentity

**Status:** Accepted
**Date:** 2026-06-18
**Deciders:** Project owner (Aigle_2)

## Context

VAIVOX diverges meaningfully from WhisperAttack(API). A user could have an
upstream WhisperAttack install *and* VAIVOX on the same machine. Today the two
would collide on:

- the **VoiceAttack plugin GUID** `{1AD02372-145E-4143-BBBE-AC7575595C24}`
  (`VoiceAttackPlugin/WhisperAttack/WhisperAttack.cs`) — VoiceAttack identifies
  plugins by GUID, so a shared GUID confuses VA;
- the **data directory** `%LOCALAPPDATA%\WhisperAttack` (`whisper_attack.py`),
  which holds custom config *and* the log file → silent clobber;
- the **TCP ports** 65432 / 65433;
- display names, namespace, window/tray title, single-instance guard.

There are **no fork users yet**, so we have a free hand and no migration debt.

## Decision

Target **clean separation**: a distinct product that never clobbers upstream
files or confuses VoiceAttack, with the explicit non-goal of running both STT
servers *simultaneously*.

Centralize **all** identity in a single `ProductIdentity` constant resolved at the
composition root:

| Field | Value |
|-------|-------|
| Product name | `VAIVOX` |
| Plugin GUID | a freshly generated GUID (not the upstream one) |
| Data dir | `%LOCALAPPDATA%\VAIVOX` |
| Log file | `VAIVOX.log` |
| Inbound / plugin ports | dedicated defaults, settable via config |
| Agent API port | dedicated localhost port, **off by default** (ADR-0010) |
| Window / tray / single-instance key | `VAIVOX` |

## Options Considered

### Option A: Clean separation (chosen)
Change GUID + data dir + identity surface. Ports may keep their defaults because
we never run two servers at once.
**Pros:** kills the double-install pain at low cost; one place to change identity.
**Cons:** must touch every hardcoded `WhisperAttack`/GUID/port once.

### Option B: Full simultaneous coexistence
Also requires configurable ports on **both** sides, including a rewrite of the C#
plugin (which currently hardcodes everything).
**Pros:** could run both at once.
**Cons:** real work for a near-useless scenario (two STT servers competing for the
mic).

### Option C: In-place rename without centralization
**Cons:** hardcoded identity re-creeps; collisions return with the next feature.

## Trade-off Analysis

The actual user pain is config/log clobber (data dir) and VA GUID confusion — both
solved by Option A. Simultaneous coexistence (Option B) buys nothing real for a
push-to-talk mic pipeline. Centralization (vs Option C) is what keeps the
separation from eroding.

## Consequences

- Easier: no cross-product clobber; identity changes in one file.
- Harder: a one-time sweep of hardcoded strings/ports/GUID.
- Note: a new GUID means VoiceAttack sees a **new** plugin; the bundled `.vap`
  profile must target it, and re-pointing TX buttons is expected (no users yet).

## Action Items

1. [ ] Introduce `ProductIdentity` in the config/composition layer.
2. [ ] Generate a new plugin GUID; update the C# plugin + bundled profile.
3. [ ] Route data-dir, log, ports, titles through `ProductIdentity`.
