# ADR-0001: Adopt a layered monorepo with a contracts package

**Status:** accepted
**Date:** 2026-10-02

## Context
Three owners build three stages (RTL -> Selection -> Diagram -> SVG). They must work in
parallel without blocking each other, and the wiring between stages must be easy to read.

## Decision
One uv workspace with six packages: `rtl2d-contracts`, `rtl2d-l1`, `rtl2d-l2`, `rtl2d-l3`,
`rtl2d-pipeline`, `rtl2d-eval`. Principles (docs/bootstrap.md §1):

1. Layers know only the contracts, never each other. No cross-layer imports.
2. Wiring happens only in `pipeline/`.
3. Every layer boundary has a fixture under `corpus/<case>/expected/`.
4. Experiments are isolated by directory (`layers/*/experiments/`), not by branch.
5. Walk the skeleton end to end first (pipe4 with fixtures), then grow it.

Contracts are pydantic models; JSON Schema is exported from them and committed.
Dependency rules are enforced by `tests/test_layer_boundaries.py`.

## Consequences
- Any contract change needs an ADR, a version bump, re-exported schemas and updated fixtures.
- A non-Python layer can only consume the exported JSON Schema (see bootstrap §9).
