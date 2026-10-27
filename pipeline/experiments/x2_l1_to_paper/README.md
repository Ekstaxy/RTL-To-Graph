# x2_l1_to_paper: real RTL → L1 → L3 paper-figure drawings

**Owner:** pipeline (L1 → L3 integration)  **Date:** 2026-10-12  **Branch:** `integ/l1-l3`

## Hypothesis
L3's paper-figure engines (`layers/l3_draw/experiments/e3_paper_engines`) were only tried on
hand-written specs. If L1's output carries enough (units, connectivity, the teacher's names,
groups and interfaces, generate-array counts), the same engines draw real RTL as system
figures with no hand-written per-design data.

## Method
```
RTL ─ L1 front end (pyslang, heuristic mode, no API, no Run Store)
    ─ teacher labels from layers/l1_extract/outputs/teacher-v1/raw.tar.gz  (teacher_v1.py)
    ─ x1 bridge.build (stand-in for L2) → e0 diagram + meta                (unchanged)
    ─ adapter.py → e3 input (diagram + sidecar)
    ─ e3: grammar → engine → libavoid → paper renderer → measure + round trip
```
- **Teacher labels without the store.** The archive holds L1's own `ModuleResult` per module
  (`anchors_full.json`). `teacher_v1.patched_annotate` runs L1 in heuristic mode and swaps in
  the archived teacher result for every module whose anchor / group / interface IDs all exist
  in today's entity table. All 9 designs matched fully (0 mismatches).
- **Adapter** (the L2 stand-in's job; no layer's `src/` changes):
  1. the bridge's wiring helpers (`split` / `join`) collapse into direct connections;
  2. a teacher group with several instances becomes a titled container; a group with one
     instance plus glue logic is one box named by the group (x1 RULES S2);
  3. ARBITER / DECODER groups and names like crossbar, interconnect, bus, decode, switch get
     `role: bus` (drawn as bars);
  4. `count` from generate-array folding (ADR-0003) becomes ×N stacks;
  5. the teacher's boundary interfaces (ADR-0003) group the terminals.
- **Checks.** The bridge's diagram passes all e0 v0.1 rules. The adapted diagram passes rules
  1–7; rules 8–9 (one width per net, one driver per port) are relaxed because collapsing
  splits and joins makes nets that ADR-0002 calls out of scope (bit slices, multi-driver);
  the count is in `stages.json`. Every drawing is round-tripped against the adapted diagram.
- **Designs** (x1 `eval_set.json`, RTL from `layers/l1_extract/data/rtl`): picorv32_picosoc,
  dark_darksocv, verilog-ethernet udp_complete / ip_complete / eth_mac_1g_rgmii_fifo,
  verilog-axi axi_crossbar, verilog-axis axis_ram_switch, serv_serv_top, wb2axip_axim2wbsp.
- **Engines** (from e3): elk, dot, hola, busbar, cola, grid, d2_tala, d2_dagre.

```
uv run --package rtl2d-l1 --with nodejs-wheel --with ortools python \
    pipeline/experiments/x2_l1_to_paper/run.py --jobs 6
```
Needs the e3 tools under `runs/.tools` (see e3 README). Output: `runs/x2_l1_to_paper/`
(`inputs/` with bridge, meta, adapted diagram and sidecar per design; `stages.json`;
`svg/`, `png/`; `results.json`; `gallery.html`; `blind.html`).

## Pass / abandon criteria
- Every design goes through L1, bridge and adapter with no error, and teacher labels apply.
- Every measured drawing: 0 round-trip issues.
- Readability is decided on `blind.html`, as in e3.

## Results
2026-10-12: 9 of 9 designs through the whole chain (L1 + bridge + adapter under 1 s each);
teacher labels applied on all 9 (0 ID mismatches); 72 drawings, all ok; **0 round-trip
issues; 0 hard violations** for every measured engine on every design.

| design | units after adapter | arrows | crossings elk / dot / hola / busbar / cola |
|---|---|---|---|
| picorv32_picosoc | 5 | 41 nets | 5 / 1 / 3 / 2 / 2 |
| dark_darksocv | 6 | 31 | 3 / 4 / 4 / 3 / 3 |
| ethernet udp_complete | 4 | 153 | 3 / 7 / 8 / 2 / 2 |
| ethernet ip_complete | 4 | 101 | 5 / 2 / 1 / 2 / 2 |
| ethernet eth_mac_1g_rgmii_fifo | 4 | 52 | 1 / 1 / 3 / 2 / 0 |
| axi_crossbar | 2 | 88 | 0 / 0 / 1 / 0 / 0 |
| axis_ram_switch | 11 | 265 | 7 / 6 / 5 / 10 / 4 |
| serv_serv_top | 11 | 114 | 94 / 83 / 99 / 123 / 110 |
| wb2axip_axim2wbsp | 3 | 64 | 1 / 1 / 1 / 1 / 0 |

- picosoc reads like the PULPissimo-style figure: CPU, UART, SPI flash controller and
  On-chip RAM on an "Address decode and read mux" bar, terminals iomem / irq / uart /
  flash_spi on the border. darksocv and axis_ram_switch get the teacher's names, ×4 stacks
  and bars from RTL alone.
- serv_serv_top is dense (a bit-serial CPU whose units all talk to each other): every
  engine has 80+ crossings. It needs the datapath view (x1 paper.py), not the system view.
- Several tops have only 2–4 children (axi_crossbar, the Ethernet stacks): the top is a thin
  wrapper; a figure would draw one level deeper (x1's depth knob, `root=`), not yet wired here.

## Conclusion
L1 → L3 for system figures works today without an API call and without L2, through x1's
bridge and this adapter. What the contracts still lack to drop the stand-ins:
- **Selection** (ADR-0002 selection) carries names only; drawing needs the teacher's groups,
  interfaces and connectivity, which today come from L1 internals (`results_full`, graph).
- **Diagram v0.2** (ADR-0003) covers `count` and boundary `interfaces`; still missing are
  containers from teacher groups (`parent_id` is there, but L2 must create the group
  blocks), a hub role (bar), and nets for bit slices / several drivers.
- The Run Store is not needed when teacher-v1 is used; a new design outside teacher-v1 gets
  heuristic labels (generic names) until the teacher is run on it.
