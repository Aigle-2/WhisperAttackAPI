# ADR-0007: Tooling, build & CI standard

**Status:** Accepted
**Date:** 2026-06-18
**Deciders:** Project owner (Aigle_2)

## Context

The project ships with ad-hoc tooling: split `requirements.txt` /
`requirements-api.txt`, three `build_*.cmd` scripts plus `build_exe.ps1`, no
linting, no type checking, no automated tests in CI, and version strings scattered
in source. The rewrite calls for a modern, reproducible, enforced standard.

## Decision

Adopt the following baseline:

- **Packaging:** `pyproject.toml` (PEP 621), `src/` layout, dependencies with a
  `[full]` extra for the optional local `faster_whisper` backend (replacing the
  two `requirements*.txt` files).
- **Quality gates:** `ruff` (lint + format), `mypy --strict`, `pytest` + coverage,
  `pre-commit`. Docstrings follow the **Google** convention, enforced via ruff's
  `D` rules on the public API.
- **Boundary enforcement:** `import-linter` contracts encode ADR-0001's dependency
  rule (domain imports no infrastructure) and fail CI on violation.
- **Build:** a single `build.py` task + a checked-in PyInstaller spec (replacing
  the `.cmd`/`.ps1` scripts). The C# plugin builds via `dotnet build`.
- **CI (GitHub Actions):** on PR → lint + type + test; on tag `v*` → build the exe,
  build the plugin, package the zip, publish a Release. Version is single-sourced.

## Options Considered

### Option A: Full modern toolchain (chosen)
**Pros:** quality is enforced, not aspirational; releases are reproducible; the
dependency rule cannot silently regress.
**Cons:** upfront setup; contributors must run the toolchain (documented).

### Option B: Minimal (`pyproject.toml` only, no gates/CI)
**Pros:** least effort.
**Cons:** no enforcement — the architecture and quality erode over time, which is
exactly the failure mode we are fixing.

## Trade-off Analysis

The whole point of the rewrite is durability. Enforcement (Option A) is what makes
the architecture survive future contributions; Option B re-creates the conditions
that produced the current state.

## Consequences

- Easier: consistent style, typed code, green-by-default boundaries, one-command
  releases.
- Harder: initial CI/tooling setup; a documented contributor workflow.
- The plugin DLL becomes a first-class CI build artifact (supports ADR-0006).

## Action Items

1. [ ] Author `pyproject.toml` + tool configs (ruff, mypy, pytest, coverage).
2. [ ] Add `import-linter` contracts for the layer boundaries.
3. [ ] Add `pre-commit` + a `build.py` + a checked-in PyInstaller spec.
4. [ ] Add the GitHub Actions PR + release workflows; single-source the version.
