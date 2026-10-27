# ADR-0002: Fill the Selection contract from L1's Stage 1 anchors

**Status:** proposed (L1 owner; needs L2 and L3 owners' review)
**Date:** 2026-10-03

## Context
`rtl2d_contracts.Selection` is still an empty v0-draft (bootstrap §4.1: `schema_version`,
`design`, `signals[]`, `modules[]`, each entry with `name`, `reason`, `source_refs`).
L1 now has a working Stage 1 implementation (`layers/l1_extract`, spec in
`layers/l1_extract/docs/SPEC.md`). For each module it produces `anchors.json`, which
contains:

- `module_summary`;
- anchors, each with `id`, `name`, `role`, `importance`, `trace`, `why`, `confidence`, and
  evidence line numbers `lines`;
- groups and interfaces;
- `region.json`: the RTL nodes the trace keeps and the arrows between anchors;
- `fsm.json` (optional): the FSMs found in the design.

Until the contract has fields, `rtl2d_l1.extract()` already returns the mapping below as a
plain dict and emits a `SelectionDraftWarning` (it does not fail). The pipeline can keep
using `--fixture l1` until the model exists.

## Decision (proposed)
Map Stage 1 output onto the v0-draft fields first and add nothing else. Additions come in a
second step.

| Selection field | from Stage 1 |
|---|---|
| `design` | `anchors.json.design` |
| `modules[].name` | module name |
| `modules[].reason` | `module_summary` |
| `modules[].source_refs` | file and line range of the module |
| `signals[].name` | hierarchical anchor name (`<instance path>.<name>`) |
| `signals[].reason` | `role` and `why` |
| `signals[].source_refs` | `file:line` for each `lines` entry (evidence lines, checked by L1's validator) |

**Step 2 candidates** need L2 to say what it needs, then a `SCHEMA_VERSION` bump:

- `role`, `importance` and `confidence` as typed fields. L2 could use them to choose block
  kinds and the level of detail.
- `groups`, which suggest how to cluster blocks.
- `anchor_edges`, abstract arrows between anchors.
- FSM descriptions.

Once step 1 is accepted, L1 fills `corpus/pipe4/expected/selection.json` from its own
output, and a person reviews it before it becomes the fixture.

## Consequences
- As soon as step 1 is merged, L1 wraps its dict in `Selection(...)` and drops the warning.
- L1 keeps its richer `anchors.json` and `region.json` as internal files under `runs/`. The
  contract carries only what L2 consumes.
- Anything step 2 adds goes through the bootstrap §4.3 process: ADR, version bump, schemas,
  fixtures.
