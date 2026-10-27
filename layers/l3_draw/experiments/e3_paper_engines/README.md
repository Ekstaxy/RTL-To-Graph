# e3_paper_engines

**Owner:** L3 owner  **Date:** 2026-10-11

## Hypothesis
e2 drew paper-type inputs in a schematic style (ports on boxes, one wire per net) and only
compared ELK variants with our own engines. The look of the memo's four figures (ISSCC /
VLSI style system diagrams) needs two things e2 did not have:

1. **the paper grammar** before layout: one arrow per block pair (double-headed for
   read/write), clock and reset hidden, buses as bars, ×N stacks, titled and coloured
   subsystems, terminals on the chip border;
2. **layout algorithms built for that kind of picture**, not only ELK layered: the memo
   names HOLA (human-like orthogonal), constraint layout (WebCoLa), grid / packing
   (osage, D2 grid, CP-SAT), and libavoid for object-avoiding routing.

Claim: with the grammar fixed, at least one non-ELK algorithm produces drawings people
judge closer to the paper figures than ELK layered, and the measures (alignment,
compactness, crossings) point the same way.

## Measurement
Inputs (from e2, `p3lib.load`): the memo's figures `fig_system`, `fig_sfu`, `fig_gs_soc`
and its zoom panels `fig_gs_edc`, `fig_gs_mac`, `fig_sparse_core`; `earlgrey` (written from
memory in e2); `bus_star8`; `ibex`.

Pipeline: `grammar.py` turns a Diagram into the paper graph (and checks that every
(net, sink) between two items is kept in some arrow) → a placement engine (`layout.py`)
→ libavoid orthogonal routing, the same for every engine (`avoidroute.py`,
`native/avoid_run.cpp`) → the paper renderer (`paper.py`) → `measure3.py` and the round
trip `check.py`.

| Engine | What it is | Hierarchy |
|---|---|---|
| `elk` | ELK layered (reference: the e1 / e2 baseline family) | native |
| `cola` | WebCoLa 3.4: stress layout with non-overlap and nested group constraints | native |
| `dot` | Graphviz 2.43 dot, clusters | native |
| `fdp` | Graphviz fdp, force-directed with clusters | native |
| `osage` | Graphviz osage, packs clusters into an array | native |
| `hola` | HOLA (libdialect, adaptagrams master), then uniform shrink | per container |
| `busbar` | e2's bus-bar grammar | per container |
| `grid` | equal-cell rows in BFS order, 16:9 | per container |
| `cpsat` | OR-Tools CP-SAT cell grid, distance + bbox, bonus for shared rows / columns | per container |
| `d2_dagre`, `d2_elk`, `d2_tala`, `d2_grid` | D2 0.9.0 with its own renderer and router | native |

D2 drawings come out of D2 (same graph, same colours) and are **not** measured or round-
trip checked; they are there to be looked at. TALA is D2's proprietary engine: check its
licence before adopting it.

Measures (`measure3.py`, px): hard = overlapping units + units inside a foreign container
+ overlapping sibling containers + lines through a unit + lines sharing a stretch; then
crossings, alignment, compactness, 16:9 error, bends, length.

```
# one-time tools (all under the git-ignored runs/.tools)
apt-get install -y graphviz pkg-config swig autoconf automake libtool librsvg2-bin
git clone https://github.com/mjwybrow/adaptagrams runs/.tools/src/adaptagrams
(cd runs/.tools/src/adaptagrams/cola && autoreconf --install &&
 ./configure --prefix=$PWD/../../../adaptagrams && make -j8 && make install)
# the same again into runs/.tools/adaptagrams-nd with CXXFLAGS="-O2 -DNDEBUG" (see build.sh)
layers/l3_draw/experiments/e3_paper_engines/native/build.sh
uv run --no-project --with nodejs-wheel python -c "import nodejs_wheel; \
    nodejs_wheel.npm(['install','--prefix','$PWD/runs/.tools/cola','webcola@3.4.0'])"
curl -fsSL https://d2lang.com/install.sh | sh -s -- --prefix $PWD/runs/.tools/d2

# run
uv run --package rtl2d-l3 --with nodejs-wheel --with ortools python \
    layers/l3_draw/experiments/e3_paper_engines/run.py --jobs 6
uv run --package rtl2d-l3 python layers/l3_draw/experiments/e3_paper_engines/pages.py
```
Output: `runs/e3_paper_engines/` with `gallery.html` (named), `blind.html` (vote page),
`svg/`, `png/`, `results.json`.

## Pass / abandon criteria
Fixed before the matrix ran.
- Harness: grammar loses no sink, and every measured drawing passes the round trip.
- An algorithm is a candidate if it has 0 hard violations on most inputs.
- The decision is the **blind vote**, not the score. The score only flags broken drawings.
- Abandon an algorithm that the vote never picks first and that the score ranks below ELK.

## Results
2026-10-11: 9 inputs × 13 algorithms = 117 drawings in 169 s on 6 processes. All 117 ok,
grammar lost no sink, **0 round-trip issues** on the 81 measured drawings. libavoid's
nudging hit its known assertion on 3 Earl Grey layouts; the NDEBUG build was used there
(and the measures show the result: shared stretches counted as hard). HOLA threw on 3
containers (fig_sparse_core, earlgrey, ibex); those levels fell back to `grid` (noted).

Hard violations per input (0 is a usable drawing; rerun 2026-10-12 after the one-line bar
label fix; `cpsat` varies between runs because of its time limit):

| input | elk | cola | dot | fdp | osage | hola | busbar | grid | cpsat |
|---|---|---|---|---|---|---|---|---|---|
| fig_system | 0 | 0 | 0 | 2 | 4 | 0 | 0 | 0 | 0 |
| fig_sfu | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 |
| fig_gs_soc | 0 | 0 | 0 | 5 | 26 | 0 | 0 | 0 | 0 |
| fig_gs_edc | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 |
| fig_gs_mac | 0 | 0 | 0 | 3 | 5 | 0 | 0 | 0 | 0 |
| fig_sparse_core | 0 | 0 | 0 | 19 | 21 | 1 | 0 | 0 | 0 |
| earlgrey | 35 | 30 | 0 | 14 | 36 | 28 | 1 | 15 | 2 |
| bus_star8 | 0 | 0 | 0 | 0 | 5 | 0 | 0 | 0 | 0 |
| ibex | 0 | 0 | 0 | 4 | 19 | 0 | 0 | 0 | 0 |

Alignment (share of siblings in a shared row or column; figures are near 1):

| input | elk | cola | dot | fdp | osage | hola | busbar | grid | cpsat |
|---|---|---|---|---|---|---|---|---|---|
| fig_system | 0.45 | 0.00 | 0.55 | 0.00 | 0.70 | 0.65 | 0.95 | 0.95 | 0.45 |
| fig_gs_soc | 0.33 | 0.13 | 0.43 | 0.64 | 0.73 | 0.58 | 0.75 | 0.76 | 0.56 |
| fig_sparse_core | 0.44 | 0.17 | 0.48 | 0.70 | 0.76 | 0.71 | 0.90 | 0.90 | 0.63 |
| earlgrey | 0.46 | 0.39 | 0.59 | 0.59 | 0.98 | 0.67 | 0.67 | 0.78 | 0.74 |
| ibex | 0.23 | 0.09 | 0.32 | 0.18 | 0.50 | 0.71 | 0.73 | 0.73 | 0.73 |

What the numbers and the pictures say (the vote decides; this is only my reading):
- **busbar** is the only algorithm with 0 hard violations nearly everywhere *and* high
  alignment. Earl Grey under busbar reads like the OpenTitan figure: two crossbar bars,
  units in rows on both sides, ×N stacks, power domains as coloured frames.
- **HOLA** gives the most "hand-drawn" small figures (fig_sfu, fig_system): compact,
  symmetric, few bends. It crashes on some containers and is weak on Earl Grey.
- **dot** is the safest: 0 hard violations on all 9 inputs, fewest crossings on the
  large ones, but rows are not aligned (layered columns), so it looks like ELK.
- **WebCoLa** has the fewest crossings on the small figures but no alignment at all
  (0.0 to 0.2): organic, not paper-like.
- **fdp** and **osage** are not usable as is (lines through units; osage packs
  clusters well but ignores edges).
- **cpsat** is fine on small levels, 20 s per drawing, and loses on large ones.
- **D2 + TALA** (not measured) produced the cleanest large drawings by eye
  (fig_gs_soc, fig_sparse_core): orthogonal, bundled fan-outs, titled frames. D2's grid
  mode gives the table look but draws diagonal lines between cells.

Median seconds per drawing: elk 3.3, cola 2.3, dot 0.9, fdp 1.2, osage 0.7, hola 1.0,
busbar 1.0, grid 1.3, cpsat 22, d2_dagre 2.6, d2_elk 2.8, d2_tala 7.6, d2_grid 3.9.

## Conclusion
Pending the blind vote (`runs/e3_paper_engines/blind.html`). Provisional:
- The paper grammar (one arrow per pair, bars, stacks, coloured subsystems, chip-border
  terminals) does most of the work: every algorithm looks closer to the figures than e2.
- Candidates to keep for the vote: busbar, HOLA, dot, D2 + TALA. Likely to drop: fdp,
  osage, WebCoLa (no alignment), cpsat (slow, no better).
- libavoid as the common router removes e2's A* failures (0 unrouted, round trip clean);
  its nudging bug on large inputs needs the NDEBUG fallback.

Not tested: ARCOL (no public code found here), yFiles / Nlview (commercial), zoom panels
drawn next to the main figure, colour by clock domain (no field).
