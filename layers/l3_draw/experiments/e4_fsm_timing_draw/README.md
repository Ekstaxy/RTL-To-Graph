# e4_fsm_timing_draw

**Owner:** L3 owner  **Date:** 2026-10-24

L3 half of plan `docs/plan_fsm_timing.md` §2/§3 Stage 3: draw an FSM graph (FsmGraph v0.1) and
a timing diagram (TimingDiagram v0.1), and read both drawings back. Inputs are plain JSON
dicts with the keys of `pipeline/experiments/x4_fsm_timing/{fsm_spec,timing_spec}.py`; nothing
here imports pipeline, L1 or other experiments (siblings are loaded by file path, so
`x4_tools.load()` works).

## Hypothesis
1. Graphviz `dot` (LR, reset first, guard labels capped at 40 characters) gives readable state
   diagrams for the FSMs L1 finds (up to about 10 states), and every state and transition
   can be found again in the SVG by `data-rtl2d-kind/id` (G4).
2. WaveDrom draws a TimingDiagram faithfully: every drawn value, arrow and gap can be read back
   from the SVG + WaveDrom source (T5), including two clock domains of unrelated periods on one
   exact time grid, at a width people accept (about 50 px per fastest cycle).

## Measurement
- `selftest.py` draws hand-written fixtures (`fixtures.py`): a 5-state one-hot FSM with
  self-loops, a > 40-character guard and a semantic-only edge; an FSM with a `*` edge
  already expanded plus an unnamed unreached state; a semantic-only FSM with unknown guards;
  a single-domain valid/ready/data diagram with a gap and 2 arrows; a two-domain diagram
  (periods 10 / 14) with a gap and a cdc arrow; a uart_tx-like diagram with an FSM state lane.
- `fsm_roundtrip.check` (G4), `wave_check.check` (T5), `fsm_measure.measure`,
  `wave_measure.measure`; the PNGs (`--png`, rsvg-convert) are looked at.
- In the pipeline, `x4_run.py --part fsm|timing` calls the same functions on the M1 / M2b
  designs.

```
uv run --package rtl2d-l3 python layers/l3_draw/experiments/e4_fsm_timing_draw/selftest.py --png
uv run --package rtl2d-l3 python layers/l3_draw/experiments/e4_fsm_timing_draw/fsm_draw.py FSM.json OUT
uv run --package rtl2d-l3 python layers/l3_draw/experiments/e4_fsm_timing_draw/wave_draw.py \
    TIMING.json OUT --node runs/.tools/x3/node/bin/node \
    --cli runs/.tools/wavedrom/node_modules/wavedrom-cli/wavedrom-cli.js
```
Outputs: `runs/e4_fsm_timing_draw/{fsm,timing}/`.

## Pass / abandon criteria
- Pass: G4 100% and T5 100% on the fixtures and, later, on every FSM / diagram x4 draws
  (M1: G4 100% on the gated FSMs; M2b: T5 renders 8/8); 0 node overlaps; 0 label collisions
  and 0 label overflows in the timing fixtures; two-domain diagrams <= 2x the width of the
  same cycles drawn single-domain.
- Abandon WaveDrom multi-domain drawing (fall back to one diagram per domain with a shared tick
  ruler, plan §6) if a real two-clock design (afifo, axis_async_fifo) is unreadable at that
  width or T5 fails on it.

## Design

### FSM (`fsm_draw.py`)
- DOT `rankdir=LR`; reset state first (BFS order from it), entry arrow from a point node,
  double border and light fill for reset; circles when every name is <= 8 characters, else
  ellipses for all states.
- Label: name, then a small encoded value line (`5'b00100`; hex `N'h..` above 12 bits, or 16
  for one-hot); unnamed states italic; unreached states dashed grey.
  Name and value sit in a two-row HTML table with a 3-unit spacer row (names with `_`
  touched the value line otherwise). HTML label text doubles backslashes: Graphviz 2.43
  expands escString (`\N` = node name) inside HTML labels even after `&#92;`.
- Edge label: the guard, whitespace-normalised, wrapped at 22 characters, truncated at 40
  with an ellipsis (recorded in the draw result's `simplifications`); the full guard, kind
  and `seen_by` go into the edge `<title>`. `"1"` / `always` unlabelled; `unknown` dashed with
  a red `?`. Edges with `seen_by` lacking `syntactic`/`both` are purple; empty `seen_by` is
  drawn normally and listed in the legend as "provenance unknown".
- Footer (HTML table, one font per row because Graphviz places mixed-font runs by its own
  width estimate): `module.state_reg`, encoding / width / counts, check summary
  (`checks.semantic.semantic_check`, `checks.yosys.status`, `checks.completeness.status`),
  `REJECTED: reason` for rejected graphs, and only the legend lines that occur.
- SVG: Graphviz ids `state:<id>` / `tr:<id>`; post-processing adds `data-rtl2d-kind`,
  `data-rtl2d-id` (+ `data-rtl2d-src/dst/name`). Mermaid `stateDiagram-v2` side file.

### Timing (`wave_draw.py`)
**Time grid.** Every wave character is one posedge-to-posedge cycle of its lane's domain.
Sampling follows x4 `vcd.py` / `timing_bridge`: the sample of cycle c is the value just before
posedge c (last change strictly before the edge), i.e. the value held during
[posedge c-1, posedge c). It is drawn in the column that ends at posedge c, so a register
changes exactly at the edge that loads it (checked on x4 uart_tx: state_q 0->1 at t=45000 in
the VCD is drawn at 45000). A testbench input driven at a negedge is drawn changing at the
posedge before it (cycle quantisation, up to half a period early). All lanes share one WaveDrom base unit of
`u = gcd(all periods, 2 x every domain's start offset)` simulation time units; a domain of
period P is drawn with per-signal `period = P/u` and `phase = offset/u x hscale` (WaveDrom
phase shifts in half-unit bricks; non-integer periods are not supported by WaveDrom's brick
generator, hence the integer grid). Single domain: `u = period`, one character per cycle,
default skin, integer `hscale` (1..3) so that every bus label fits. Multi-domain: narrow skin,
then the wave area is squeezed horizontally after rendering so one fastest cycle is 48 px
(wider if a label needs it); text is counter-scaled, strokes use `non-scaling-stroke`. Domains
that start later than the earliest one get leading pad cycles drawn as `x` (not sampled).

**Gaps.** Hidden cycles are never drawn as values (the x4 bridge's window-break gaps can hide
changes). In each domain the hidden cycles that stay drawn are hatched (`x`, not sampled); the
second of them carries the `|` glyph (also hatched), so a gap reads "hatch + //". The removed
time is `k x lcm(periods)` with the largest k that leaves 2 hidden columns (hatch + glyph) per
domain, or 1 when some domain hides only one cycle (then that domain shows only the hatch). In
a single domain that is `hidden - 2` cycles removed. If k = 0 the gap is drawn uncompressed and
labelled "(not compressed)". A Gap that hides no cycle in any domain (adjacent window breaks)
gets no glyph, no label and no legend entry, only an empty
`<g data-rtl2d-kind="gap" data-rtl2d-empty="1">` for the round trip; recorded. The label `+N cyc` (multi-domain: `+N clkA / +M clkB`, the declared counts)
is a hidden-node self-edge label in an unnamed row above the lanes, over the glyph. Holes in a domain's cycles
that no Gap declares are drawn as "(undeclared)" gaps and recorded.

**Arrows.** Hidden (upper-case, Latin-1 and Greek capitals: 80 letters, WaveDrom only labels
lower-case nodes) node letters at the src / dst columns; `~>` next cycle, `-|>` same cycle,
`-~>` cdc, re-coloured orange and dashed after rendering. Arrow ends must be drawn sample
columns; otherwise the arrow is skipped and recorded.

**Head / foot.** Head: `id — protocol scenario`. Foot (left-aligned by post-processing):
stimulus kind, seed, simulator version and the sampling convention; second line: legend of the arrow kinds and gap glyph
that occur. Group label: `clock T=period`.

**Tags.** `wavelane_<i>_0` -> `data-rtl2d-kind="lane"` (or `clock`, id `clk.<domain id>`);
arc paths -> `arrow` with the Arrow id and `data-rtl2d-arrow=kind`; gap labels -> `gap` with
id `g.<index in TimingDiagram.gaps>` (`g.implicit.<n>` for undeclared ones); domain group
bracket + label -> `domain` (domain id); the gap-label row -> `gaprow`; head -> `title`; foot ->
`footer`; legend line -> `legend`. FSM: states, transitions, `entry` (the reset arrow, id
`entry`), `entry_point` (the point node, id `init`), `legend` (the footer <g>, id `footer`). The WaveDrom JSON
carries an `"rtl2d"` key (grid, per-signal column map `[kind, cycle, gap, mark]`, arrow / gap
metadata, simplifications) that WaveDrom ignores and `wave_check` / `wave_measure` read.

### Checks
- `fsm_roundtrip.check(g, svg)`: `{ok, missing, extra, duplicated, wrong_ends, untagged,
  states, transitions}`; a transition end that is not a state, or any untagged Graphviz
  node / edge `<g>`, fails G4.
- `wave_check.check(d, svg, wavejson)`: presence of every lane / clock / arrow / declared gap
  exactly once; replay (decode each wave string + data list and compare with every drawn
  sample; enum names for state lanes; ellipsis-shortened labels must be prefixes); SVG lane
  texts == WaveDrom data list; arrow letters on their (lane, cycle) column; one `|` glyph per
  gap glyph column per lane; hidden / pad columns decode to the hatched `x`. The `rtl2d` column
  map is not trusted: its sample cycles must equal the cycles of `Lane.values`, every sample
  column recomputed from the grid (unit, offsets, periods, removed gap time) must end at its
  `Sample.t`, and each signal's WaveDrom `period` / `phase` must match the grid. Negative tests
  (tag removed, SVG label edited, sample changed, sample columns relabelled `hold`, an extra
  undrawn sample, grid offset shifted, wrong / dangling transition end, transition untagged)
  are all caught; the last four run in `selftest.py`.

## Results
2026-10-24 (after review fixes), `selftest.py --png`, all in `runs/e4_fsm_timing_draw/`:

| fixture | check | size | measures |
|---|---|---|---|
| fsm_onehot (5 st, 9 tr) | G4 ok | 667x276 pt | 0 crossings, 1 label overlap (estimate), 3 back edges, 2 loops, 1 guard truncated |
| fsm_star (5 st, 10 tr) | G4 ok | 758x449 pt | 0 crossings, 0 label overlaps |
| fsm_unknown (4 st, 5 tr) | G4 ok | 517x222 pt | 0 crossings, 0 label overlaps |
| timing_single (4 lanes, 2 arrows, 1 gap) | T5 ok | 878x289 px | u=10, hscale 1; 14 shown + 20 hidden cycles (18 removed, 2 hatched); 0 collisions / overflows / crossings |
| timing_two_domain (10 / 14) | T5 ok | 1519x379 px | u=2, narrow, squeeze 0.48; gap removes 4 x lcm 70 (28 wclk, 20 rclk), 2 hatched columns each; wclk 26 shown + 30 hidden, rclk 18 + 22 |
| timing_fsm_lane (enum lane) | T5 ok | 1420x319 px | hscale 2 (state names), 0 collisions |

Real x4 TimingDiagrams (18 JSONs from a review run of x4: uart_tx, skidbuffer, afifo,
axis_async_fifo, incl. a 3-gap uart_tx state lane and a 0-hidden-cycle gap): T5 18/18, 0 label
collisions / overflows. Scratch stress runs (not shipped): periods 10 / 7 with phases 5 / 3 (u = 1), 32-bit labels
fit after scaling, T5 ok; 40 same-cycle arrows + an undeclared hole + an enum value with no
name: T5 ok, each recorded; a two-domain gap too short for one lcm: drawn uncompressed and
recorded; a 14-state / 40-transition one-hot FSM with quotes, `<`, backslashes in names and
guards and `status=rejected`: G4 ok, 3878x1223 pt, 29 crossings (readable only zoomed in).
Speed: the whole self-test (3 Graphviz + 3 WaveDrom renders and checks) takes about 0.5 s.

## Conclusion
Keep as the M1 / M2b drawing stage. Open points: dense FSMs (> 10 states, many returns to
reset) need the M4 ELK engine and the blind vote; FsmGraph has no per-edge output field, so
Mealy outputs are not drawn; real afifo / axis_async_fifo diagrams must still confirm the
squeezed multi-domain grid is readable (else plan §6 fallback).
