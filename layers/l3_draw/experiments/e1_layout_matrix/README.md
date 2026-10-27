# e1_layout_matrix

**Owner:** L3 owner  **Date:** 2026-10-03

## Hypothesis
The design-space document (`../rtl_block_diagram_design_space.md`) makes four claims that
had only been checked on hand-placed sketches:

1. A layered engine with no design knowledge (N1) is a usable baseline but breaks the
   main data trunk.
2. Stage and lane information from L2 (N2) fixes that.
3. Clock and reset drawn as lines cause most crossings; hiding them (N2, N5) removes them.
4. Picking the best of several candidates by a score (N4) beats any single engine.

This experiment runs every combination of placer, router, port-side rule and presentation
on every input from `e0_reference_inputs`, and measures the result.

## Measurement
```
uv run --package rtl2d-l3 --with nodejs-wheel python \
    layers/l3_draw/experiments/e1_layout_matrix/run.py --tier all
uv run --package rtl2d-l3 python layers/l3_draw/experiments/e1_layout_matrix/report.py
```
Output in `runs/e1_layout_matrix/` (not committed): `results_{a,b,c}.csv`, `summary.md`
(all tables), `index.html` (baseline and best drawing per input), `svg/<input>/<combo>.svg`.

ELK and Graphviz are optional; combinations that need a missing engine are skipped.
One-time install, both under the git-ignored `runs/.tools/`:
```
uv run --no-project --with nodejs-wheel python -c "import nodejs_wheel; \
    nodejs_wheel.npm(['install','--prefix','runs/.tools/elk','elkjs@0.9.3'])"
conda create -y -p runs/.tools/gv -c conda-forge graphviz
```

A combination is `placer+router+sides+presentation`.

| Choice | Levels |
|---|---|
| Placer, own (`place.py`) | `lay` plain layered; `lay_ctl` control blocks inferred from kind/class and put in a row on top; `grid` columns and control row from hints; `*_wrap` the same folded towards 16:9 |
| Placer, existing (`ext.py`) | `elk` (ELK layered 0.9.3), `elk_ns` (network-simplex node placement), `elk_mo` (model order), `elk_part` (partitions from stage hints), `elk_wrap` (ELK's own wrapping), `dot` (Graphviz 14, positions only) |
| Router (`route.py`) | `naive` elbows, no avoidance; `astar` own maze router, shortest nets first; `astar_cls` data nets first; `astar_cls2` plus one rip-up pass; `native` ELK's routes |
| Port sides | `we` inputs left, outputs right; `ctl_n` control, clock and reset inputs on top |
| Presentation | `wires` every net a line; `implicit` clock and reset as dots; `stubs` clock, reset and nets with 4+ sinks as named stubs |

Metrics (`metrics.py`). Hard violations: unrouted sink, wire through a block, two nets on
the same line, a wire ending on another net, overlapping blocks, a block inside a container
it does not belong to. Soft: crossings, crossings involving a data net, bends, wire length,
share of data sinks reached with no bend, canvas size. Score is lexicographic: hard, data
crossings, crossings, bends, length. `render.roundtrip` parses each SVG back and compares
it with the Diagram.

Tiers: **a** all 216 combinations on the 35 base inputs; **b** nine combinations on all
245 input variants, plus hint variants (full, partial, wrong, none) and an input-order
check; **c** the 190 invalid inputs.

The Diagram and hints formats are the experiment-local ones from e0, not contracts.

## Pass / abandon criteria
- Round-trip passes for every drawing, and every invalid input is refused. Otherwise the
  harness is wrong and nothing else counts.
- A claim holds if the totals over the relevant inputs move in the stated direction.
- Abandon an own engine if an existing one is at least as good on every kind of input.

## Results
2026-10-03, 11 635 runs in about four minutes on 24 processes.

- Tier a: 7 560 runs; 6 468 ok, 1 080 not applicable (hint-based placer, input without
  hints), 12 ELK internal errors. Round-trip failures: 0. Tier c: 190 of 190 refused.

**Placers** (all routers, presentations and inputs they ran on; rank 0 is best):

| Placer | No hard violation | Mean rank | Straight data sinks |
|---|---|---|---|
| `elk_mo` / `elk` / `elk_ns` | 97% | 0.19 / 0.20 / 0.23 | 57% / 57% / 49% |
| `elk_part` | 93% | 0.19 | 68% |
| `elk_wrap` | 97% | 0.34 | 52% |
| `grid` | 81% | 0.39 | 57% |
| `lay` / `lay_ctl` | 82% / 83% | 0.41 / 0.41 | 47% / 47% |
| `dot` | 67% | 0.56 | 23% |
| `lay_wrap` / `lay_ctl_wrap` / `grid_wrap` | 72% / 70% / 61% | 0.58 / 0.57 / 0.59 | 42% / 42% / 51% |

**Routers:** `native` (ELK) 100% clean; `astar_cls` 92%; `astar` 89%; `astar_cls2` 88%;
`naive` 37%. The rip-up pass did not help (rank 0.39 against 0.40) and doubles the time.

**Claims 1 to 3, on the six pipeline inputs** (`we` sides, totals):

| Combination | `wires`: data crossings / crossings / length px | `implicit` | `stubs` | Straight data sinks (`wires`) |
|---|---|---|---|---|
| `elk+native` (N1) | 136 / 349 / 146 465 | 64 / 76 / 52 089 | 31 / 31 / 24 529 | 78 of 96 |
| `elk_part+native` (N2 inside ELK) | 13 / 247 / 183 127 | 16 / 24 / 55 645 | 14 / 14 / 25 983 | 89 of 96 |
| `grid+astar_cls2` (N2, own) | 69 / 154 / 79 448 | 47 / 58 / 43 512 | 16 / 18 / 31 656 | 81 of 96 |
| `lay+astar_cls2` (no hints, own) | 69 / 161 / 107 792 | 47 / 49 / 66 704 | 10 / 20 / 51 464 | 75 of 96 |

- Claim 1 holds. On `pipe8_fwd2` plain ELK moves S7, P6 and P7 off the trunk.
- Claim 2 holds. Stage hints cut ELK's data crossings from 136 to 13.
- Claim 3 holds. Hiding clock and reset alone takes plain ELK from 349 crossings to 76.

**Claim 4** (all nets as wires, 35 inputs): baseline `elk+native+we+wires` totals 467 data
crossings, 710 crossings, 298 804 px. Best candidate per input: 210, 388, 258 918. No
placer wins everywhere; ELK variants reach the best score on 16 inputs at most, own
`lay` on 10, `dot` on 5.

**Fixed canvas:** median distance from 16:9 on inputs with 8+ blocks is 2.5 for `lay` and
`grid`, 1.2 for `elk`, 0.6 to 0.7 for the own `*_wrap`, 0.85 for `elk_wrap`. Wrapping
costs 10 to 20 points of clean runs and more crossings.

**Input variants** (tier b):

- `no_meta` (no `kind`, no `class`): `implicit` hides nothing, so `elk+native+we+implicit`
  goes from 412 crossings back to 710. `stubs` still works, because it also looks at fan-out.
- Hints reversed: straight data sinks fall from 59% to 7% (`grid`) and 69% to 35%
  (`elk_part`); nothing detects that the hints are wrong. Half the hints missing: 59% to 35%.
- Input order: shuffling the lists changes the SVG for 32 of 35 inputs with every engine.
  Sorting by ID first makes all 35 identical.
- `x2` (two copies in one diagram): own placers with a control row fall to 47% to 66%
  clean; ELK stays at 94% to 100%.
- Edge cases (empty diagram, no nets, self loop, pass-through, widths to 4096, non-ASCII
  and markup labels, unknown kinds): no engine crashed on any of them. A container with
  its own ports gives one hard violation with the own router's rip-up pass.

**Engine problems found:**

- Own placers lay out leaves flat and draw containers as bounding boxes. On `ibex` (four
  containers) `lay` puts 4 to 7 blocks inside the wrong container and `lay_ctl` 11 to 13;
  `grid` 0 to 1; ELK and Graphviz 0.
- Own A* on ELK's tighter placement leaves sinks unrouted on `ibex`, `plic`, `pipe4_hier`.
- ELK partitioning throws `NullPointerException` on `fsm_datapath` (6 runs); ELK wrapping
  throws on `pipe4` and `pipe8_fwd2` (6 runs).
- Time: ELK about 0.8 s per drawing, mostly Node start-up. Own A* is 0.1 s on small
  inputs and up to 21 s on the largest (`ibex`, `pipe16_w64`) in pure Python.

**Format gaps met while drafting the five cases from figures** (for ADR-0002 and the hints
ADR; no contract was changed):

- No way to say "this block is repeated N times" (RV timer tick generator, PLIC targets).
- No bundles: UART's ten interrupts and each TL-UL bus are single wide nets here.
- Rule 4 does not let a signal pass through a container port.
- `class` needed `bus` and `status` besides data, control, clock, reset.
- `stage_index` does not order blocks inside one stage; `grid` adds its own ordering.
- A `lane: control` block inside a container cannot go to the top row.
- UART's RX path runs right to left in the reference figure; hints have no flow direction.

## Conclusion
Keep ELK as the placement engine and feed it stage hints as partitions. Do not promote
the own placers: on pipelines `grid` has more data crossings than `elk_part` (69 against
13), and without hints the own placers break on hierarchy.
Keep the own A* router only as a fallback; ELK's routes had no hard violation except three
runs on `fsm_datapath`.

What changed in our understanding:

- Presentation matters more than the engine. Hiding clock and reset removes more
  crossings than any change of placer, and it depends on `class` being filled in.
- Hints must be checked before use; wrong hints are worse than none.
- L3 has to sort its input by ID, or the drawing depends on list order.
- The candidate-and-score approach is worth building: it halves data crossings against
  the single baseline, and the harness here already is that mechanism.

Not tested: HOLA / ARCOL, libavoid, CP-SAT placement, D2 / TALA, label collisions,
whether the score agrees with what engineers prefer, and inputs drafted from RTL rather
than from figures.
