# ADR-0003: Diagram contract v0.2 — block multiplicity, net labels, boundary interfaces

**Status:** proposed
**Date:** 2026-10-10
**Builds on:** ADR-0002 (diagram minimal core). Numbering note: the repo has two ADR-0002s
(stage1's `0002-selection-from-stage1-anchors.md` and stage3's `0002-diagram-minimal-core.md`);
this ADR takes 0003 and the clash should be resolved by renaming one of them when the stage
branches merge.

## Context
`pipeline/experiments/x1_l1_to_l3` drew 35 held-out corpus designs from L1 output in the
v0.1 contract and compared four renderers on crossings, overlaps, bends and two blind
readings (`results/blind_votes.md`). Three things that real architecture figures always show
cannot be expressed in v0.1, so the experiment carried them in a side file (`meta.json`):

1. **Repeated units.** Generate arrays (`s_ifaces[0..3].adapter`) are drawn once with "×4"
   in every figure checked (Gemmini "Bank 0 … Bank K", Cheshire "CVA6 0, CVA6 1 … NumCores",
   SUSpMV "…16"). Folding them is the single largest readability gain measured: 22 → 1.7
   crossings per net on `axil_crossbar_rd`, 29 → 0.7 on `axis_ram_switch` (R13). v0.1 has
   no field for the count, so a folded block loses the information that it stands for N.
2. **Net labels.** Figures label arrows with the *interface* they carry ("RoCC Cmd",
   "instr", "data"), never with signal counts. A bundle made by the renderer (R12) has no
   name in v0.1; the experiment derived one from L1's teacher interfaces, which the contract
   does not carry either.
3. **Boundary interfaces.** Figures group boundary ports by interface (an AXI channel, a
   stream, a serial link) and draw one stub per interface (Ibex, CV32E40P, Cheshire). v0.1
   ports are individual; the grouping exists only in L1's `Interface` entries.

These are all presentation facts about *existing* objects. None changes topology, so the
six v0.1 validation rules stay as they are.

## Decision
Add three optional fields. Every one has a default that reproduces v0.1 behaviour, so a v0.1
file is a valid v0.2 file.

| Object | Field | Type | Default | Meaning |
|---|---|---|---|---|
| Block | `count` | int ≥ 1 | 1 | The block stands for `count` identical instances. L3 draws `count > 1` as a stacked box with "×N" (S7). Ports and nets describe one instance. |
| Net | `label` | str \| null | null | Text drawn on the net, when it is a named bundle or an interface. L3 never invents a label; signal counts are not labels (figure check, S3). |
| Diagram | `interfaces` | list[Interface] | [] | Named groups of **boundary** ports: `{id, label, protocol, port_ids}`. L3 draws one stub per interface (S4). `protocol` is a free string in v0.2 (`VALID_READY`, `MEMORY_BUS`, `STREAM`, `SERIAL`, `SIMPLE`, as L1's taxonomy names them). |

Validation additions (`validate.py`, same style: a list of issues, never raises):
7. `interfaces[*].port_ids` name existing boundary ports (`owner_block_id` null); a port is
   in at most one interface.

`schema_version` becomes `"0.2.0"`. Nothing in v0.1 is renamed or removed.

### Who produces what
- L1 → L2: `count` from generate-array folding (`members` on the entity table), `interfaces`
  from the teacher's `Interface` entries. Both already exist in L1's output.
- L2: may set `label` on nets it bundles; passes `count` and `interfaces` through.
- L3: consumes all three; must not fail when they are absent.

### Not decided here
- Layout hints (`stage_index`, `stage_boundary`, `lane`, `flow_role`) stay experiment-local
  (e1 `hints.json`). The x1 experiment showed they map onto what L1 knows, but they belong
  to a layout contract, not to the diagram.
- Block *kind* vocabulary (`memory`, `pipeline_reg`, `mux`, `alu`, …) stays a free string.
  The x1 bridge's structural classifier is a candidate for a later ADR once L2 exists.
- A per-net `interface_id` (a net that belongs to a boundary interface) would let L3 route
  interface traffic together; deferred until a renderer needs it.

## Consequences
- `corpus/*/expected/*.diagram.json` stay valid; `schema_version` must be bumped when they
  are regenerated.
- `export_schema.py` output changes (three optional fields); downstream JSON Schema users
  see additive changes only.
- The x1 bridge can drop `meta.json` for these three facts once the fields land; the
  bridge's `fold_arrays` becomes the reference producer of `count`.

## Evidence
- `pipeline/experiments/x1_l1_to_l3/README.md`, rounds 3–4; `RULES.md` ("checked against
  nine real figures"); `results/blind_votes.md`; `results/v7_*.json`, `results/v8_*.json`.
