# x3_tool_compare: the same RTL through every runnable RTL → diagram tool

**Owner:** pipeline  **Date:** 2026-10-17  **Branch:** `integ/l1-l3`

## Question
What do existing open-source RTL → diagram tools draw for the RTL that x2 drew with
rtl2diagram, and where does our output differ?

## Method
- **RTL.** `picosoc` (picorv32) and `darksocv` (darkriscv), with x2's file lists and tops
  (`designs.json`). Each tool reads the same copy under `runs/x3_tool_compare/rtl/`.
- **Ours.** x2's drawings, copied from `runs/x2_l1_to_paper/svg/`, from two engines picked from
  x2's `results.json` score (lexicographic: hard violations, crossings, alignment, …):
  - **elk** (detailed level): best mean rank on x2's system-view designs (2.67 of 6), and the
    same ELK layered algorithm that netlistsvg, d3-hwschematic and DigitalJS use.
  - **busbar** (paper level): beats hola on both designs (picosoc 2 vs 3 crossings; darksocv
    ranked 1st of 6).
- **Each tool runs as its users run it.** The Yosys script, viewer config and skin come from the
  tool's own source or README; `tools.json` records each recipe. Deviations from a tool's
  default are listed there under `deviation` and shown on the page.
- Browser-only renderers (d3-hwschematic, DigitalJS, Digital-IDE) run in headless Chromium
  (Playwright). Their SVG is taken from the page, fitted to its content, with the page CSS that
  applies to it inlined.
- Yosys 0.70+145 and Verilator from OSS CAD Suite 2026-10-16; sphinxcontrib-hdl-diagrams
  uses its own yowasp-yosys 0.70.

## Run
```
pipeline/experiments/x3_tool_compare/install.sh          # once; installs into runs/.tools/x3
R="uv run --no-project --with playwright==1.49.1 python pipeline/experiments/x3_tool_compare/run.py"
$R --set top                                             # -> out/, results.json
uv run --package rtl2d-l1 --with nodejs-wheel --with ortools python \
    pipeline/experiments/x3_tool_compare/ours_modules.py  # ours for the module set
$R --set module                                          # -> out_module/, results_module.json
$R --set recompare                                       # -> out_recompare/, results_recompare.json
uv run --no-project python pipeline/experiments/x3_tool_compare/gallery.py   # all three pages
```
`--only a,b --designs x` reruns a subset and keeps the other rows; `--skip-done` continues an
interrupted run. Pages: `runs/x3_tool_compare/index.html` (top modules, each tool's default),
`module-like.html` (leaf modules), `recompare.html` (top modules, each tool's most minimal
option). Each is self-contained; SVGs over 1.5 MB are embedded as PNG previews
(`runs/x3_tool_compare/preview/`). `runs/` is git-ignored, so the committed copies live in
`docs/x3_tool_compare/`; refresh them with
`cp runs/x3_tool_compare/{index,module-like,recompare}.html docs/x3_tool_compare/`.

**Memory.** WSL2 gets half the host RAM (7.6 GB here). TerosHDL on picosoc peaks near 2 GB, and
several such renders at once crashed the WSL VM. `run.py` therefore runs every tool in its own
cgroup (`systemd-run --scope -p MemoryMax=… -p MemorySwapMax=0`; 3 GB, 3.5 GB for TerosHDL), so an
oversized render is killed and reported as a failure, and tools run one at a time. Do not run
two `run.py` sets, or research scripts that render, in parallel.

## Tools
| Run | Skipped (why) |
|---|---|
| netlistsvg, Yosys show, Yosys viz, d3-hwschematic, DigitalJS + yosys2digitaljs, sphinxcontrib-hdl-diagrams (yosys-blackbox and netlistsvg), Symbolator, TerosHDL, Digital-IDE 0.4.6, Verilator vl_hier_graph | HDElk (hand-written JSON, no RTL input); VSV (repo not accessible); RTLViz, FEntwumS, Kactus2 (excluded by choice); Chisel diagrammer, easysoc, Rocket Chip Diplomacy (FIRRTL / Scala input only) |

hwtGraph is not run: it converts HWT (Python) designs. d3-hwschematic's own Yosys importer is its
Verilog path. CréVinn is a method; its runnable part is Verilator's `vl_hier_graph`.

## Findings while getting the tools to run
- **File order matters to Yosys.** `picosoc.v` must be read before `picorv32.v` (it `` `error ``s
  if `PICORV32_V` is already defined). x2's list had the other order, which pyslang accepts.
- **darksocv needs its firmware image.** `darkram.v` does `$readmemh("../src/darksocv.mem")`
  relative to the run directory; the file is copied beside the RTL.
- **d3-hwschematic vs current Yosys.** Without `write_json -compat-int`, today's Yosys writes
  parameters as bit strings and the importer throws `Incorrect width00…01`.
- **yosys2digitaljs has no top option** (`hierarchy -auto-top`); `picorv32.v` holds several
  candidate tops, so its script is run with `hierarchy -top <top>` instead.
- **Digital-IDE 0.5.0** (current Marketplace release) ships all 102 netlist-viewer files as
  0-byte placeholders; 0.4.6 is used. Its webview needs VS Code's `--vscode-*` theme variables
  (Light+ values are injected).
- **sphinxcontrib-hdl-diagrams** pins Sphinx 4.5 but pulls helper extensions that need Sphinx ≥ 5;
  they are pinned back.
- **Verilator** needs `-Wno-fatal` (picosoc leaves picorv32 pins unconnected).
- **TerosHDL on picosoc** overflows Node's default stack in netlistsvg's recursive `gather()`
  ("Maximum call stack size exceeded"; the extension shows "graph exceeds the maximum size").
  `node --stack-size=8000` lets it finish: 161 s, 5.2 MB SVG, about 2 GB RAM.
- **netlistsvg** (both upstream and TerosHDL's fork): dev dependencies no longer resolve; runtime
  dependencies are installed and the TypeScript compiled with tsc 3.9.

## Results (2026-10-17)
21 of 22 tool × design runs drew a diagram; the page is `runs/x3_tool_compare/index.html`.

| What comes out | Tools |
|---|---|
| Block diagram of named functional units | **ours** (elk, busbar) only |
| Cell/gate-level schematic of the top (submodules as boxes) | netlistsvg, Yosys show, d3-hwschematic, DigitalJS, sphinx (both), Digital-IDE |
| Whole design flattened onto one sheet | TerosHDL (picosoc 5.2 MB, darksocv 2.3 MB SVG) |
| Module hierarchy only | Verilator vl_hier_graph |
| Port symbol only | Symbolator (darksocv: shows `ifdef` / `endif` / `__SDRAM__` as ports, a regex-parser artefact) |
| One blob listing wires | Yosys viz with default options |

TerosHDL needed a larger Node stack for picosoc (see above). One failure remains, as the tool
fails: **Digital-IDE 0.4.6 on darksocv** throws `TypeError: … reading 'clk_in'` and stays on its
loading screen. Cause: its flow reads every file without `hierarchy -top`, and `darkspi.v`
instantiates `spi_master`, which is not in the RTL; the viewer reads that cell's
`port_directions` for every module, used or not.

## Module-level set (module-like.html)
The lowest module of one file from each SoC, a leaf with no child instances, chosen 2026-10-17:
**spimemio_xfer** (in spimemio.v, beside spimemio, which instantiates it; 211 Yosys cells) and
**darkuart** (darkuart.v alone, which includes ../rtl/config.vh; 76 cells). Ours and every tool
read only that one file.

Every tool runs in its most minimal mode that still draws the module's structure, and nothing
flattens or lowers it (no `flatten`, techmap or AIG; d3-hwschematic's own `synth -run coarse`
keeps word-level cells):
- **Yosys viz**: most merged effort that still splits the module, clock/reset excluded
  (spimemio_xfer -6, darkuart -9; at -9 spimemio_xfer is one blob).
- **DigitalJS**: `transformCircuit`. **TerosHDL**: fork mode `off` + `opt`.
- The rest keep their default. Yosys show's top-level option (select submodule cells) and
  d3-hwschematic's (collapse the top into one box) have nothing to act on in a leaf; the others
  have no option at all (see recompare).

Ours: `ours_modules.py` runs x2's path (L1 heuristic + teacher-v1 labels → x1 bridge → e3).
23 of 24 cards draw. **Digital-IDE 0.4.6 on darkuart** fails: its symbol set (`dide.skin`) has no
`$shift` / `$shiftx` symbol, which darkuart's shift register needs, and the renderer throws.

**Bridge fix (pipeline/experiments/x1_l1_to_l3/bridge.py).** Ours' elk drawing of spimemio_xfer
first failed with an ELK `UnsupportedConfigurationException`. Cause: `flash_csb` is an
`output reg` loaded only from top ports (`din_valid`, `din_ready`) and read only by another port
register (`flash_clk`). No teacher group owned a driver, so the bridge wired the input port
`din_valid` straight to the output port `flash_csb`, and the register vanished. e3's elk engine
pins both interface pins (`din`, `flash_spi`; mixed directions, side io) to the first layer, and
ELK cannot lay out an edge between two first-layer nodes. The fix: after the existing
driver vote, an output register still without a block follows the blocks of its neighbours,
counting output ports already placed (drivers first, then readers), to a fixed point. flash_csb
now belongs to "Transfer sequencing" and elk draws it. Re-bridging x2's nine designs: eight are
byte-identical; picosoc changes in one place, where `iomem_valid` (an address compare,
picosoc.v:112) moves from an anonymous join block into "Address decode and read mux". x2's saved
picosoc drawings (used as ours on index.html and recompare.html) predate the fix.

## Recompare (recompare.html)
Each tool's own most-simplifying option, found by one research agent per tool in its source and
docs, tested on both designs, then checked by an independent reviewer (`tools.json` "minimal"
holds option, evidence, numbers and caveats; research files under `runs/x3_tool_compare/research/`).

| Tool | Own option | picosoc | darksocv |
|---|---|---|---|
| Yosys show | selection: submodule cells of the top + their wires | 116 → 45 nodes | 146 → 35 nodes |
| Yosys viz | `-6`, `-x` clock/reset, `-G` inter-instance wires | 1 blob → 8 nodes | 7 → 8 nodes, 4 instances separate |
| d3-hwschematic | top starts collapsed (`_children`) | 66 → 1 node (box + ports) | 68 → 1 node |
| DigitalJS | `transform.transformCircuit` ("Simplify diagram") | 93 → 85 devices | 71 → 46 devices |
| TerosHDL | fork `hierarchy.enable: "off"` + Yosys `opt` | 5.2 MB → 117 KB | 2.3 MB → 99 KB |
| netlistsvg, sphinx ×2, Symbolator, Digital-IDE, vl_hier_graph | none (drawing kept) | | |

No tool has a block-level mode: every "minimal" output is still cells and wires (or a single
box). netlistsvg's skin flags (`constants`/`splitsAndJoins` off) shrink the drawing only by
dropping connections, so they are not counted. TerosHDL's `off` mode is the fork's own default,
but the VS Code extension hard-codes `all`; a user can only type `opt`.
