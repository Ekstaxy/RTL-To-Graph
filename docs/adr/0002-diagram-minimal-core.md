# ADR-0002: Diagram contract v0.1 — minimal core (blocks, ports, nets)

**Status:** proposed
**Date:** 2026-10-03

## Context
`rtl2d_contracts.diagram` is an empty stub and `corpus/pipe4/expected/` has no files. The
seed files that bootstrap step 1 treats as the source of truth (`pipe4.diagram.json`,
`pipe4.layout-hints.json`) are not in the repo, so there is nothing to derive fields from.

L3 needs a fixed input format now, for two reasons:

- to write the minimal renderer and the round-trip check (bootstrap step 3);
- to build an L3 test set: 10–15 hand-reviewed Diagrams drafted from open-source RTL
  (OpenTitan, Ibex, CVA6, NEORV32), plus variants generated from them.

L2 needs the same format as its output target. Both sides are blocked until it exists.

This ADR fixes only the topology that every later feature depends on ("S1" in
`layers/l3_draw/experiments/rtl_block_diagram_design_space.md`). The field names are the
ones already listed in `docs/bootstrap.md` §4.1; nothing new is introduced.

## Decision

### Model
`Diagram` has four top-level fields. Unknown fields are rejected (`extra="forbid"`).

| Object | Field | Type | Required | Meaning |
|---|---|---|---|---|
| Diagram | `schema_version` | str | yes | Must equal `SCHEMA_VERSION`. |
| Diagram | `blocks` | list[Block] | yes | |
| Diagram | `ports` | list[Port] | yes | |
| Diagram | `nets` | list[Net] | yes | |
| Block | `id` | str | yes | Stable ID. |
| Block | `label` | str | yes | Text drawn on the block. |
| Block | `kind` | str \| null | no | Free string in v0.1. L3 draws an unknown or missing kind as a rectangle. |
| Block | `parent_id` | str \| null | no | Enclosing block; null means top level. |
| Port | `id` | str | yes | Stable ID. |
| Port | `owner_block_id` | str \| null | yes | Block the port belongs to; **null means a port of the design itself** (a boundary port). |
| Port | `direction` | `"input"` \| `"output"` | yes | Seen from the owner (or from the design, for boundary ports). |
| Port | `width` | int ≥ 1 | yes | Bits. |
| Port | `class` | str \| null | no | Free string in v0.1. |
| Net | `id` | str | yes | Stable ID. |
| Net | `source` | str | yes | Port ID of the single driver. |
| Net | `targets` | list[str], ≥ 1 | yes | Port IDs of the sinks. |
| Net | `width` | int ≥ 1 | yes | Bits. |
| Net | `class` | str \| null | no | Free string in v0.1. |

`class` is a Python keyword; the pydantic field is `class_` with alias `class`.

IDs match `^[A-Za-z0-9_.\-]+$` and are unique across blocks, ports and nets together.

### Checks in `validate.py` (returns a list of issues, never raises)
1. IDs are unique across the whole Diagram.
2. Every `parent_id` and `owner_block_id` names an existing block; `parent_id` has no cycles.
3. Every `source` and every entry in `targets` names an existing port.
4. A net's `source` is a block **output** or a boundary **input**; each target is a block
   **input** or a boundary **output**.
5. `width` of a net equals the `width` of every port on it.
6. A port is the source of at most one net and a target of at most one net.

### Example
```json
{
  "schema_version": "0.1.0",
  "blocks": [
    {"id": "b.s1", "label": "S1", "kind": "comb", "parent_id": null},
    {"id": "b.p1", "label": "P1", "kind": "register", "parent_id": null}
  ],
  "ports": [
    {"id": "p.in_data", "owner_block_id": null, "direction": "input", "width": 32, "class": "data"},
    {"id": "b.s1.a", "owner_block_id": "b.s1", "direction": "input", "width": 32, "class": "data"},
    {"id": "b.s1.y", "owner_block_id": "b.s1", "direction": "output", "width": 32, "class": "data"},
    {"id": "b.p1.d", "owner_block_id": "b.p1", "direction": "input", "width": 32, "class": "data"}
  ],
  "nets": [
    {"id": "n.in_data", "source": "p.in_data", "targets": ["b.s1.a"], "width": 32, "class": "data"},
    {"id": "n.s1_y", "source": "b.s1.y", "targets": ["b.p1.d"], "width": 32, "class": "data"}
  ]
}
```

### Differences from bootstrap §4.1
- `scope` on ports is left out. Its meaning is not written down anywhere; boundary ports
  are expressed by `owner_block_id: null` instead.
- `kind` and `class` are optional free strings, not enums. A closed vocabulary needs its
  own ADR once L2 knows what it can produce.

### Out of scope (each needs a later ADR)
- `LayoutHints` and `LayoutOverrides` (stage, lane, flow role, bundles, presentation).
- `inout` ports, multi-driver nets, bit slices and concatenation.
- `source_refs`, provenance, lock levels.
- `Selection`, `Issue`, `DrawResult`.

### Version and corpus
- `SCHEMA_VERSION` goes from `0.0.0` to `0.1.0`; schemas are re-exported and
  `contracts/CHANGELOG.md` gets an entry.
- `corpus/pipe4/expected/diagram.json` is written by hand in this format and recorded in
  `corpus/pipe4/notes.md` as hand-written, with its reviewer.

## Consequences
- L3 can start on the renderer and round-trip check; L2 has a concrete output target.
- L3 test cases drafted from open-source RTL can be validated by `rtl2d check`.
- With hints out of scope, L3 can only produce the generic layered layout (N1 in the
  design-space document) until the hints ADR lands.
- Free-string `kind` and `class` mean typos are not caught by the schema. Tightening them
  to enums later is a breaking change for existing fixtures.
- Designs with bidirectional pins or bit-sliced buses cannot be represented exactly yet;
  L2 has to leave them out or approximate, and say so.
- If the original `pipe4.diagram.json` seed turns up and disagrees with this ADR, the
  difference has to be settled before this ADR is accepted.

## Open questions for the three owners
1. Is `owner_block_id: null` acceptable for boundary ports, or should `scope` come back?
2. Should rule 6 (one net per port) hold, or may an output port drive several nets?
3. Do `kind` and `class` stay free strings for v0.1, or do we fix a short list now?
