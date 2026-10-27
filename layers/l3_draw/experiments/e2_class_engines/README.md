# e2_class_engines

**Owner:** L3 owner  **Date:** 2026-10-10

## Hypothesis
The memo 《第三層製圖：依規模分流的圖類型與對應演算法》 claims that the layout engine must be
chosen **per container by diagram class**, from indicators computed on the spec, because
figures express topology by *position* as the scale goes up (bus bars, grids, ×N stacks)
and by *wires* as it goes down (schematics, datapaths). Concretely:

1. (X1) On SoC-overview inputs (class D) a layered engine fails: the hub becomes a tall
   node with every wire fanning out of it. Turning the hub into a bar and packing the
   attached blocks in rows along it gives a readable, compact drawing.
2. (X2) ELK's `highDegreeNodes.treatment` does not rescue the layered engine on hubs.
3. (X3) One ELK call with per-node `elk.algorithm` (root rectpacking, children layered)
   does the "outer packing, inner layering" recursion natively.
4. (X4) The memo's six indicators and thresholds (§1.3) classify containers the way a
   person would.
5. (X5) For subsystem diagrams (class C) bottom-up per-container layout (ELK
   SEPARATE_CHILDREN or own composition) is at least as good as one global layered run.
6. (X6) Exact grid placement (CP-SAT, after Yoghourdjian et al. 2015) is usable at our
   sizes (20–60 items per level).
7. (E) Regular arrays should be placed by procedure, not by a general layouter.

## Measurement
Inputs (`inputs.py`, 28 cases in e0 format plus a *sidecar* for what the format lacks):
the four figures pasted from the memo (`fig_system`, `fig_sfu`, `fig_gs_soc` with its two
zoom panels `fig_gs_mac` / `fig_gs_edc`, `fig_sparse_core`), OpenTitan Earl Grey from
memory (`earlgrey`, marked approximate), a 4×4 systolic array, a 60-node DAG, and 19 e0
seeds covering classes A–E. Every case passes e0's `spec.validate`.

Engines (`run.py`): e1's `elk` / `elk_part` baselines; `elk_hd`, `elk_sep`, `rect_root`,
`topdown` (one ELK call with per-node options, `elkx.py`); `grid`, `busbar`, `auto`,
`cpsat` (bottom-up composition, `compose.py`, with level engines `elklevel.py`,
`busbar.py`, `arrays.py`, `cpsat.py`). Composition routes globally with e1's A*.

Metrics: e1's `measure` (hard violations, crossings, bends, length) plus `metrics2.py`:
`align` (share of siblings sharing a row or column), `compact` (block area / bbox area),
`aspect_err`. The score is class-specific (A/B: e1's tuple; C adds compactness; D ranks
crossings, alignment, compactness, length; E alignment, aspect, crossings). Every drawing
is checked by e1's `roundtrip`.

```
uv run --package rtl2d-l3 python layers/l3_draw/experiments/e2_class_engines/inputs.py --check
uv run --package rtl2d-l3 python layers/l3_draw/experiments/e2_class_engines/classify.py --table
uv run --package rtl2d-l3 --with nodejs-wheel --with ortools python \
    layers/l3_draw/experiments/e2_class_engines/run.py --jobs 6 --cpsat-seconds 30
uv run --package rtl2d-l3 python layers/l3_draw/experiments/e2_class_engines/report2.py
uv run --package rtl2d-l3 python layers/l3_draw/experiments/e2_class_engines/blind.py
```
Output in `runs/e2_class_engines/` (git-ignored): `inputs/`, `classify.md`, `results.csv`,
`results.json`, `svg/<input>/<engine>.svg`, `summary.md`, `index.html`, `blind.html`.
ELK is installed as in e1's README (`runs/.tools/elk`, elkjs 0.9.3 under nodejs-wheel).

elkjs 0.9.3 probe (`knownLayoutAlgorithms`): `layered`, `rectpacking`, `box`, `stress`,
`force`, `mrtree`, `radial`, `disco`, `sporeOverlap`, `sporeCompaction`, `fixed`, `random`.
There is **no** `topdownpacking` algorithm; top-down layout is the option
`elk.topdownLayout` on `rectpacking`. `elk.layered.highDegreeNodes.*` and
`elk.hierarchyHandling` exist.

## Pass / abandon criteria
Fixed before the matrix ran.

- Harness: every drawing has 0 round-trip issues, or nothing else counts.
- X1 holds if `busbar` beats `elk` on the class-D score on the majority of class-D inputs
  with 0 hard violations; abandon `busbar` if an ELK variant is at least as good on every
  class-D input.
- X2 holds (treatment helps) only if `elk_hd` changes the score on the hub inputs.
- X3 holds if `rect_root` returns child layouts laid out by `layered` inside a
  `rectpacking` root with no ELK error.
- X4: report the confusion table for the memo's thresholds; a threshold is changed only
  with the reason written here.
- X5: per class-C input, which of `elk`, `elk_sep`, `auto` wins on the class-C score.
- X6: CP-SAT returns a feasible placement within 30 s per level on all three sizes;
  report objective vs bound.
- E: `auto` (procedural) beats `elk` on alignment with 0 hard violations.

## Results
2026-10-10, 28 inputs × 10 engines = 280 runs in 324 s on 6 processes (WSL, 8 cores).
All 280 rows: status ok (17 `elk_part` n/a without stage hints), **0 round-trip issues,
0 errors**. Full tables: `runs/e2_class_engines/summary.md`; drawings: `index.html`;
vote page: `blind.html` (28 inputs, not yet voted on).

**Best engine per input by the class score** (hard violations first, then the class
criteria; `elk` = e1's baseline):

| root class | inputs | winners |
|---|---|---|
| A | 9 | elk 4, grid 3, elk_sep 1, elk_part 1 (grid and elk_sep differ from elk by a few crossings; same engine family) |
| B | 6 | elk_part 3, grid 2, elk 1 |
| C | 9 | elk 5, elk_sep 2, grid/auto 2 (ibex, fig_system) |
| D | 2 | **busbar 2** (bus_star8, fig_gs_soc) |
| E | 2 | **auto (arrays) 2** |

**X1, bus bar vs layered (class D).** Holds on the two inputs whose *root* is class D,
fails on Earl Grey:

| input | engine | hard | crossings | align | compact | aspect err | canvas px |
|---|---|---|---|---|---|---|---|
| bus_star8 | elk | 0 | 81 | 0.50 | 0.20 | 1.46 | 488×722 |
| bus_star8 | elk_sep | 0 | 48 | 0.40 | 0.23 | 1.64 | 472×744 |
| bus_star8 | grid (no bar) | 7 | 97 | 0.90 | 0.38 | 1.13 | 496×544 |
| bus_star8 | **busbar** | 0 | **16** | 0.90 | 0.29 | 0.04 | 664×408 |
| fig_gs_soc | elk | 0 | 100 | 0.36 | 0.06 | 0.32 | 2176×1457 |
| fig_gs_soc | elk_sep | 0 | 92 | 0.43 | 0.05 | 0.20 | 2360×1518 |
| fig_gs_soc | grid | 1 | 165 | 0.56 | 0.09 | 0.21 | 2200×1008 |
| fig_gs_soc | **busbar** | 0 | **41** | 0.59 | 0.09 | 0.09 | 2288×1128 |
| earlgrey (root C, `main` D) | elk | 0 | 1255 | 0.36 | 0.04 | 1.17 | 2154×2569 |
| earlgrey | elk_sep | 0 | 915 | 0.41 | 0.04 | 1.35 | 2056×2764 |
| earlgrey | busbar | **11** | 470 | 0.72 | 0.15 | 0.11 | 1600×1016 |

The bar transform removes 60 to 80 % of the crossings and gives the 16:9, grid-aligned
look of the figures (the bus_star8, fig_gs_soc and earlgrey drawings read like the memo's
figure 1: full-width interconnect, per-subsystem bars, ×4 stacks). On Earl Grey the own
A* router leaves 11 of 244 sinks unrouted, all of them nets that leave the `main` domain
(interrupts and alerts into PLIC / alert handler, pinmux links); ELK's router never fails.
The `grid` control (same rows, no bar) is *worse* than ELK on every D input: the gain is
the bar, not the rows.

**X2, high-degree treatment.** `elk_hd` never changes the crossing count on a hub input
(earlgrey 1255 → 1255, bus_star8 81 → 81, fig_gs_soc 100 → 103) and lengthens wires on
the DAGs (comb_dag40 28 762 → 34 498 px). The treatment extracts *trees* hanging off a
node; request/response pairs are cycles, so nothing is extracted. Abandoned.

**X3, per-node algorithms in one ELK call.** The option is honoured: with root
`rectpacking` and containers `layered` the containers come back laid out in layers and
packed by the root. But rectpacking ignores edges, so every root-level edge (20 of 73 sinks
on fig_gs_soc, 30 on earlgrey, 24 on ibex) comes back without a route; A* on top of ELK's
routes then collides with them (hard 20 / 40 / 58). `topdown` additionally scales child
layouts (ibex shrinks to 749×387 px with 100 violations). Both are usable only as
*placement* engines inside the own composition, never as one-shot drawings. The
recursion hypothesis of memo §5.1 holds for placement and fails for routing.

**X4, classification.** `classify.md` holds the table. Memo thresholds verbatim: 38 of
66 container levels match the hand-assigned class, 53 land on the same engine (A and B
share ELK). Two indicator fixes were needed before thresholds mattered: (1) "identical
structure" must include identical neighbours, otherwise every random DAG folds into one
×20 group and becomes class E; (2) the hub degree must count data/bus nets only, otherwise
a controller fanning `en` to eight registers is a bus. Calibrated rules (`cal`): 54 of 66
match, 58 on the same engine. What remains is the A/B/C boundary on small containers
(3 units of kind `comb` are "cells" to the rules and "units" to a reader) and class-C
levels that hold a FIFO or an adder (prim_ratio ≥ 0.15 → B). None of these change the
engine. Thresholds unchanged; the A rule was changed to "only cells, no containers, ≥ 5
children" and is checked before the hub rule.

**X5, class-C engines.** On the nine class-C roots the global layered run (`elk`) wins 5,
`elk_sep` 2 (fig_gs_edc, earlgrey), own composition (`auto`, ELK per level + A*) 2 (ibex:
60 → 50 crossings, fig_system: 13 → 12 and half the wire length). Per-container layout is
not better on C inputs with few cross-container nets, and A* is the weak link when there
are many. The figure look (fig_sfu with its ×4 stack, Inst. Ctrl grouped) is reached by
both `elk` and `auto`.

**X6, CP-SAT.** The exact model (integer cells, no overlap, weighted Manhattan length +
bounding box) is optimal within seconds for levels of ≤ 9 items and stalls at 13 to 30
items: `FEASIBLE` after the 30 s budget with the bound at 30 to 50 % of the objective
(earlgrey `main`, 30 items: 12 325 vs bound 3 915; fig_gs_soc root, 17 items: 4 532 vs
1 956). Its layouts are compact (fig_system 560×464 px vs 1 074×454) but it does not know
about ports, so wires wrap around boxes and crossings rise (fig_system 13 → 18). Bench on
the plain DAGs: see `runs/e2_class_engines/cpsat_bench.txt` (table below).

| input | items | limit s | status | objective | bound | gap | wall s | hard | cross |
|---|---|---|---|---|---|---|---|---|---|
| comb_dag20 | 30 | 10 | FEASIBLE | 4776 | 972 | 80% | 11 | 0 | 29 |
| comb_dag20 | 30 | 60 | FEASIBLE | 3684 | 1136 | 69% | 60 | 0 | 26 |
| comb_dag40 | 60 | 10 | FEASIBLE | 36136 | 2242 | 94% | 12 | 0 | 189 |
| comb_dag40 | 60 | 60 | FEASIBLE | 12798 | 2258 | 82% | 64 | 21 | 122 |
| comb_dag60 | 83 | 10 | FEASIBLE | 49756 | 408 | 99% | 32 | 14 | 484 |
| comb_dag60 | 83 | 60 | FEASIBLE | 22620 | 3072 | 86% | 72 | 39 | 258 |

**E, arrays.** Procedural placement wins both: systolic4x4 0 crossings (ELK 15), align
1.0, inputs above the columns and beside the rows; crossbar4x4 11 crossings (ELK 22), the
masters in a row over the slaves with the full-connect fan below, as the PULP figure.

**Time.** Median seconds per drawing: elk 2.6, elk_sep 1.4, busbar 1.8, auto 1.8,
cpsat 2.1; worst cases are A* on the big composed inputs (grid 208 s, busbar 106 s on
earlgrey) and CP-SAT budgets (156 s).

## Conclusion
- **Keep the class split, but only three engines matter:** ELK layered for A/B/C, the bar
  transform for D, procedural grids for E. The memo's prediction that the layered engine
  fails on D holds (bus_star8 81 → 16 crossings, fig_gs_soc 100 → 41), and the `grid`
  control shows the bar, not the row packing, is what helps.
- **Do not promote the own composition router.** A* leaves sinks unrouted on Earl Grey and
  is 50× slower than ELK. Next step: keep the bar transform as a *pre-layout* step and let
  ELK route it (hub as a wide node with fixed N/S ports, devices with partition hints),
  the way x1 found that transforms before ELK generalize and own placers do not.
- **Abandon `elk_hd`, `topdown`, and one-call `rect_root`** as drawing engines. Keep
  `rect_root` only if a router for the root level is added.
- **CP-SAT is not usable above ~12 items per level** at 30 s and ignores ports; abandon as
  a placer, keep the model as a reference for alignment constraints.
- **Classification:** compute hub degree on data/bus nets, require identical neighbours
  for a replication group, and treat A/B/C as one engine family; `role` and `replicate`
  in the sidecar are what actually decide the drawing.
- **What changed in our understanding:** the figure grammar is mostly a *presentation*
  of hubs and arrays, not a different placement algorithm; and routing, not placement, is
  where the own code fails.

Not tested: HOLA / ARCOL and libavoid (C++), D2 / TALA, the vote page with human readers,
real-RTL inputs through x1's bridge (run store absent on this machine), colour.

## Format gaps (ADR candidates; kept in the sidecar, never in the Diagram)
- `role: bus | crossbar | noc` on a block: triggers the bar transform. Without it the
  classifier guesses from `hub_max`, which also fires on a CSR with many outputs.
- `replicate {count, shape}` on a block or container: the "×N" stack. The spec is
  written folded (as x1's bridge does); L3 never hides a block.
- `arrays [{shape, members, flow}]`: explicit 2-D placement for class E.
- `view_level` per container, `expand` (zoom panel), `group_by` (power / clock domain).
- `kind: comb` is used for both a gate and a whole unit ("Gaussian Transformer"); the
  A/B boundary cannot be computed from kinds alone.
- Colour semantics (subsystem / function / clock domain) and spec text in labels
  ("SRAM (208 KB)") have no field.
