# Paper-style drawing rules (black and white)

**Status after the held-out evaluation (README):**
- **Generic, use everywhere:** R8, R9, R12 (generalized: three or more connections between two blocks, or between a block and a teacher interface, become one bundle) and the views.
- **Pipeline-only:** R1, R2, R7 and R11. Use them when L1 finds pipeline registers; they need lane pairing, which is structural (`bridge.lanes_of`), not by name.
- R3–R5 are only shapes.

These rules were distilled from the system-architecture figures that digital-design papers and
manuals use for processor pipelines:
- the Patterson & Hennessy 5-stage MIPS/RISC-V datapath;
- the lowRISC Ibex block diagram;
- the OpenHW CVA6 overview.

`paper.py` implements them; each rule is tagged in the code. The rules apply to any design in
which L1 finds pipeline registers. They are not specific to RV32I.

| # | Rule | Where in the figures | `paper.py` |
|---|------|----------------------|------------|
| R1 | Data flows left to right. Stages are columns, titled on top in bold (IF, ID, EX, MEM, WB). | P&H, CVA6 | `columns()`, stage titles from the teacher's PIPELINE_STAGE groups |
| R2 | Pipeline registers are tall thin bars between stages, all the same height and named ("IF/ID"). Each signal crosses its bar at one height (a *lane*). | P&H (shaded bars), CVA6 | `sides()` pairs `x_in` with `x`; `layout_lanes()` |
| R3 | Memories, the register file and functional units are rectangles, named inside, with port names inside. | all three | `shape()` |
| R4 | Muxes are trapezoids with numbered inputs. The select enters from the top and does not pull the mux's position. | P&H, Ibex, CVA6 | mux select `side = "T"`; T ports are ignored in `place()` |
| R5 | The ALU is the notched trapezoid. Adders use the same shape, smaller. | P&H | `shape()` |
| R6 | Control units (decoder, hazard, forwarding) sit in a control band above the datapath, drawn as rounded rectangles. Control wires are thin and dashed. | P&H (control in blue, above), Ibex | `band` from the `lane: control` hint |
| R7 | Feedback (branch redirect, forwarding, write-back) never runs right to left through the datapath. It drops into a channel below it, or rises into one above it for control and selects, each on its own track. | P&H write-back along the bottom; forwarding below | `route()`: back edges go into the `top`/`bot` channels |
| R8 | Clock and reset are not drawn. | all three | nets of class clock/reset are dropped |
| R9 | Data is solid and control is dashed. Arrowheads mark sinks and dots mark junctions. A slash with a number marks a bus only when its width differs from the main datapath width. | P&H | `svg()` |
| R10 | Labels are short and centered. Bar names go below the bars, out of the top channel's way. | — | `shape()` |
| R11 | The main trunk is straight. A block is placed at the median height of the ports it talks to, so PC → PC+4 → IF/ID → … reads as straight lines. | P&H | `place()`: median alignment plus order-preserving packing |
| R12 | Several control signals from one block into one pipeline register are drawn as one bundle wire ("ctrl"), split out after the register. | P&H (decoder outputs as WB/M/EX bundles) | `bundle()`, presentation only |

Routing invariants (checked by `svgmetric.py`, which works on both L3's SVG and ours):
- no two nets share a collinear segment (`overlap = 0`);
- track order inside a gap respects stub/tail heights (`_colour`);
- corridors are unique per net (`corridor`).

Views (choosing what to show, done before layout):
- `full`: every block.
- `datapath`: hides the blocks in the teacher's CONTROLLER groups. This is the textbook
  "basic pipelined datapath" figure, which omits hazard and forwarding control.

## System view: checked against nine real figures (2026-10-10)

Figures read at full size this round (URLs, not copied into the repo):
SoC level: neorv32 processor (`stnolting/neorv32` README), PULPissimo (`pulp-platform/pulpissimo/doc/pulpissimo_archi.png`), Cheshire (`pulp-platform/cheshire/docs/img/arch.svg`).
Accelerator: Gemmini (`ucb-bar/gemmini/img/gemmini-system.png`), SUSpMV compute unit (arXiv 2610.10403 Fig. 5).
Core level: Ibex (`lowRISC/ibex/doc/03_reference/images/blockdiagram.svg`), CVA6 (`docs.openhwgroup.org` ariane_overview), CV32E40P (`openhwgroup/cv32e40p/docs/images/CV32E40P_Block_Diagram.png`), 2-level priority encoder (arXiv 2601.20067 Fig. 8).

What held, what did not, and the decisions:

| Rule | Verdict | Evidence | Decision |
|---|---|---|---|
| S1 rectangles, bold names | **held** (9/9) | all | keep |
| S2 containers | held, but **solid** borders with the title at the top; dashed is reserved for *optional* features (Ibex, CV32E40P) | Gemmini "Rocket"/"Gemmini Accelerator", neorv32 CPU box, Cheshire grey field | containers solid thin, title top-left; never dashed |
| S3 one labelled arrow per pair | **half held**: arrows yes, labels rarely. Labels appear only for named interfaces (Gemmini "RoCC Cmd", "RoCC PTW"; PULPissimo "instr"/"data"); signal counts never | 9/9 | drop "N sig" labels; label only interface names; width only through line weight |
| S4 boundary by interface, left/right | held for cores (Ibex memory interfaces as tall side bars; CV32E40P instruction/data interfaces); SoCs put each external interface **next to the block that owns it**, on any side (Cheshire uart* beside UART, jtag* above JTAG) | Ibex, CV32E40P, Cheshire, neorv32 | keep left/right; an interface used by exactly one block may sit beside that block (not implemented yet) |
| S5 layered grid by flow | **did not hold for SoCs.** 3/3 SoC figures and Gemmini are *bus-centred*: the interconnect is a long bar, initiators hang below it, targets/memories above it, with short vertical arrows; no block-to-block Z-routes | PULPissimo (TCDM bar, APB bar), Cheshire (AXI crossbar bar, Regbus demux bar), neorv32 (bus system box, peripheral grid, no arrows at all) | **new S9**: when one unit is a hub (crossbar / interconnect / arbiter, or degree ≥ 4 and ≥ half the units), lay out bus-centred: hub as a wide bar, initiators below, targets above, vertical arrows. Layered flow stays for everything else |
| S6 gaps / top channel / bottom channel | held where arrows exist (Gemmini DMA→L2 goes around) | Gemmini, SUSpMV | keep |
| S7 arrays "×N" | held in spirit; drawn as **first, …, last** or a row of identical boxes | Gemmini "Bank 0 … Bank K", Cheshire "CVA6 0, CVA6 1 … cfg.NumCores", PULPissimo 8 Mem Banks, SUSpMV "…16" | draw a folded array as a stacked (double-outline) box labelled "×N" |
| S8 no clock/reset, weight by width, dashed control | held (clock/reset only as a boundary stub, PULPissimo "Clock / Reset Generator" as a block) | all | keep |
| Datapath R6 control band | held, stronger: the controller is a **wide thin bar spanning the top** of the datapath (CV32E40P), and the register file likewise (Ibex) | CV32E40P, Ibex | note for the datapath grammar: control / regfile as top-spanning bars (not implemented in paper.py) |
| Datapath port names inside blocks | held (CV32E40P OpA/OpB/RD, Ibex mux inputs Imm/Reg/PC/Fwd) | CV32E40P, Ibex | keep in the datapath grammar; this is why `paper` wins blind votes on small designs |
| Stage containers / columns | held (Ibex "Instruction Fetch / Decode and Execute / Writeback" boxes, CVA6 coloured stage columns, CV32E40P IF/ID, ID/EX, EX/WB bars) | all three cores | R1/R2 confirmed |

## System view (S1–S8): the block diagram of a whole SoC / accelerator

Evidence base, stated honestly: two figures read directly this round (the SUSpMV compute-unit
figure, FPT 2026; the 2-level priority-encoder block diagram, arXiv 2601.20067) plus the
Rocket/Gemmini, PULPissimo and OpenTitan top-level diagrams from memory. arXiv's HTML
rendering dropped most figures, so this list should be checked against ten or more figures
from IEEE Xplore or authors' repositories before it is treated as settled.

| # | Rule | Seen in | `system.py` |
|---|------|---------|-------------|
| S1 | Every unit is a rectangle with a bold name. No mux / ALU symbols at this level. | all | `svg()` |
| S2 | A teacher group with several member instances is a titled container (dashed box, name top-left). A group with one instance plus its glue is one box named by the group. | 2LPE (dashed "64:6 2LPE"), Rocket tiles | `build_units()` |
| S3 | One arrow per ordered block pair, labelled with the interface name or the signal count. Opposite directions that are both bundles merge into one two-headed arrow. | Gemmini "RoCC Cmd/PTW", PULP buses | `build_edges()` |
| S4 | Boundary ports group by teacher interface (AXI channel, stream, serial): one stub per interface, inputs left, outputs right, name in bold. | OpenTitan, CVA6 | `build_edges()` boundary units |
| S5 | Layered grid left to right by data flow; cycles broken by a weighted feedback set so request paths read forward; rows aligned to neighbours. | all | `_layers()`, `_layout_level()` |
| S6 | Forward arrows Z-route in the gap before the target; long arrows that would cross a unit go over a top channel; back edges along the bottom. | Rocket, SUSpMV | `route()` |
| S7 | Repeated units (generate arrays) are drawn once with "×N". | SUSpMV ("16", "…"), 2LPE ("64×") | bridge `fold_arrays` (R13) |
| S8 | Clock and reset omitted; line weight grows with bundle width; control-only bundles dashed. | all | `svg()` |

Rule R13 (generic, both views): fold generate arrays before drawing. On the dev set this
took `axil_crossbar_rd` from 22 to 1.7 crossings per net under ELK and `axis_ram_switch`
from 29 to 0.7.

Choosing the view (`bridge.choose_view`): datapath when the top has pipeline registers or
three or more mux / ALU / adder blocks; otherwise system. The depth knob is `root`: drawing
with `root=<module>` draws that module's internals with the view chosen for *its* content.

## Added after round 5
- **R14 (datapath, from CV32E40P / Ibex):** a control unit, or a memory read and written from
  different stages, that talks to three or more columns is a thin bar across those columns
  above the datapath. Implemented behind `paper.render(bars=True)`; off by default because
  the current side-port router routes through the bars (through 0 → 70 on the CPU).
- **S10 (system, flat modules):** a CONTROLLER group that talks to ≥ 60% of the units may be
  the hub, drawn as a bar across the top with every other unit below. Implemented in
  `system._find_hub`; never chosen on dev because it adds violations. Both R14 and S10 wait
  for a router that drops verticals from a bar's bottom edge.
- **Metric note:** label collisions (`svgmetric.label_hits`) are now measured; see README
  round 5 for how little any single metric predicts a reader.
