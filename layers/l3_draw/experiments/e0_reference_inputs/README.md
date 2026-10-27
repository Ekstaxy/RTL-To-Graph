# e0_reference_inputs

**Owner:** L3 owner  **Date:** 2026-10-03

## Hypothesis
L3 can be developed and tested before L2 exists, given two things:

1. a set of reference block diagrams drawn by people (what a good output looks like);
2. a set of `diagram.json` inputs that covers small to large designs and the awkward cases.

The inputs should come from a few reviewed seed cases plus deterministic variants, not from
converting images automatically: figures leave out ports and widths, so RTL is the source
of truth and the image is only a reference.

## Measurement
No metric yet; this experiment produces data for later ones.

| Script | What it does | Output |
|---|---|---|
| `fetch.py` | Downloads figures listed in `sources.toml` (git repos, single URLs, arXiv sources). | `runs/e0_reference_inputs/refs/`, `manifest.json` |
| `run.py` | Seeds × variants (`variants.py`), each checked. Seeds: `cases/*.diagram.json`, pipelines (`gen.py`), cases drafted from figures (`real.py`), other shapes and edge cases (`topo.py`). | `runs/e0_reference_inputs/inputs/{valid,invalid,hints}/` |
| `spec.py <files>` | Checks any `diagram.json` against the format. | stdout |

```
uv run --package rtl2d-l3 python layers/l3_draw/experiments/e0_reference_inputs/fetch.py
uv run --package rtl2d-l3 python layers/l3_draw/experiments/e0_reference_inputs/run.py
```

The input format is the one proposed in `docs/adr/0002-diagram-minimal-core.md`, defined
locally in `spec.py`. It is **not** the contract; `rtl2d_contracts.diagram` is still empty.
Hints are written per seed in an experiment-local JSON (`blocks`: `stage_index`,
`stage_boundary`, `lane`; `sinks`: `flow_role`), using the field names of the design-space
document. That is not a contract either.

Variants (`variants.py`):

| Valid | Purpose |
|---|---|
| `base` | the seed itself |
| `no_meta` | `kind` and `class` all null; L3 must fall back to plain boxes |
| `no_global` | clock and reset nets and ports removed |
| `shuffled` | same graph, lists in a different order; output should not change |
| `long_labels` | long instance names, for text measurement |
| `flat` | hierarchy removed |
| `x2` | two independent copies in one diagram |

`invalid/` holds six `bad_*` variants per seed, each breaking one validation rule
(dangling target, width mismatch, duplicate ID, wrong direction, double driver, parent
cycle). L3 should refuse them.

Reference images are not committed (mixed licences). `manifest.json` records the source
URL, commit, licence and SHA-256 of each one, so the set can be rebuilt.

## Pass / abandon criteria
- Pass: `run.py` reports 0 unexpected results, and `pipe4` matches the circuit described
  in `rtl_block_diagram_design_space.md` (10 blocks, 48 ports of which 8 on the boundary,
  18 nets).
- Abandon the format if a real design from the reference set cannot be written in it
  without losing something L3 needs to draw.

## Results
2026-10-03:

- `fetch.py`: 79 figures (OpenTitan 59, Ibex 2, CVA6 13, NEORV32 5) after dropping
  identical copies. File names are filtered by keyword; some are not block diagrams
  (CI overview, state diagram) and need to be weeded out by hand.
- `run.py`: 6 seeds × 7 valid variants = 42 valid inputs, 5 to 72 blocks; 36 invalid
  inputs, all caught by `spec.validate`. 0 unexpected results.
- `pipe4`: 10 blocks, 48 ports (8 boundary), 18 nets.

2026-10-03, second run:

- 35 seeds: 6 pipelines, 5 drafted from reference figures (RV timer, UART, HMAC, PLIC,
  Ibex; 5 to 22 blocks), 14 other shapes (trees, random DAGs, bus, crossbar, ring, FSM
  with datapath, nested containers, wide fan-out), 10 edge cases. 245 valid inputs,
  190 invalid, 0 unexpected results.
- The five figure cases fit the format, with the gaps listed in
  `../e1_layout_matrix/README.md` (no replication, no bundles, no pass-through container
  ports). Port names and all widths in them are assumed, not read from RTL.

## Conclusion
Open. Still to do:

- The figure cases were drafted from pictures. No case has been drafted from RTL yet,
  so the abandon criterion is only partly tested.
- Vendor documents, papers and textbook figures: `sources.toml` has the mechanism
  (`[[url]]`, `[[arxiv]]`, a manual folder) but no entries.
