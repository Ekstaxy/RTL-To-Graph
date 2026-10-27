# x1_l1_to_l3: Stage 1 outputs → Stage 3 drawing, measured on held-out designs

**Owner:** 薛晏閎 (L1)  **Date:** 2026-10-09  **Branch:** `integ/l1-l3`, which is `origin/stage3` with `origin/stage1` merged in. The stage branches themselves are untouched.

## Hypothesis
1. What L1 extracts from RTL is enough to build stage3's experiment input (e0 `diagram.json` and hints) for any design, with no hand-written per-design data. That covers instances, connectivity, state, the teacher's groups and its interfaces.
2. Drawing rules taken from paper and manual architecture figures (RULES.md) make diagrams more readable than stage3's generic e1 layouts. "More readable" means fewer crossings and no overlapping wires or wires through blocks, on designs we did not tune on.

Our own 5-stage RV32I CPU is **only an indicator**. It is scored the same way as the other designs, but it is not the target.

## Method (fixed before looking)
- **Designs:** `eval_set.py` picks 35 third-party designs from the L1 corpus, in 7 categories:
  - hierarchical and flat CPUs: picorv32, darkriscv, serv, biriscv;
  - networking: verilog-ethernet;
  - buses: verilog-axi, wb2axip;
  - CDC/FIFO: common_cells, rtllm;
  - peripherals: uart, i2c;
  - arithmetic.
- **Split:** within each category, designs are ordered by sha1 of the name and alternate **dev (18) / test (17)**. Fixes were only allowed to look at dev. Test was run **once**, on the frozen v6.
- **Pipeline:** `evaluate.py` runs, for each design, the bridge, then each renderer in a subprocess with a timeout, then `svgmetric.py`.
- **Metrics (`svgmetric.py`):** the same code runs on every renderer's SVG.
  - crossings between different nets;
  - collinear overlaps between different nets;
  - wire segments running through a block.

  Crossings are normalized by the **bridge's net count**, which is the same denominator for every renderer, so bundling cannot hide wires.
- **Renderers:**
  - `paper`: ours;
  - `elk_part` and `elk`: the stage3 e1 baselines;
  - `elk_r12`: our pre-layout transforms (R8, R12 bundling by block pair and teacher interface) followed by stage3's `elk_part`.

## Results
**v1 (the CPU-tuned version committed first) on dev:**

| Renderer | Designs drawn |
|---|---|
| paper | 2 of 18 |
| ELK | 9 of 18 |

That confirmed v1 had overfitted to the CPU. Every v1 failure was general, not CPU-specific:
- no boundary-input handling (the CPU's only inputs were clk/rst);
- duplicate ids from generate blocks;
- slice width mismatch;
- flat designs drew nothing;
- lane pairing relied on our `x_in` → `x` port naming;
- "≤2 bits = control".

**v6, median crossings per bridge net** (0 overlaps and 0 through-block for all ELK variants):

| Split | paper | elk_part | elk | **elk_r12** |
|---|---|---|---|---|
| dev (17 drawn of 18) | 4.73 (37 overlap/through) | 3.00 | 3.00 | **0.84** |
| **test (17/17, run once)** | 2.45 (2 overlap/through) | 1.15 | 1.13 | **0.37** |
| CPU indicator | 4.23 | 5.13 | 4.53 | **3.16** |

On test, `elk_r12` is lowest in **every** category. Per-category tables are in `results/v6_*.json`.

**Blind look:** `results/blind_v6.html` shows one test design per category plus the CPU. Each has three renderings with shuffled labels; the key is at the bottom. This has not been scored yet; it needs human readers.

## Conclusion
- **Bridge: keep.** It now covers hierarchical, flat (teacher groups as logic blocks) and mixed tops, wrappers, slices and multi-driver sinks. It draws 34 of 35 designs. The one miss is a teacher-store key mismatch.
- **What generalizes is the transforms, not my placer.**
  - R12 bundling (block pair and teacher interface), R8 (hide clock/reset) and views remove most of the crossings. Applied before ELK, they beat every other variant on held-out designs.
  - My own placer and router (`paper.py`) is worse than ELK on most designs, and still has overlap bugs on large ones (37 on dev).
- **The paper look still matters for pipelines.** On the CPU, `elk_r12` has fewer crossings but no stage columns or lanes, and it reads worse by eye. Crossings do not capture R1/R2.
- **Recommendation for L3:**
  1. Adopt the pre-layout transforms: R8, R12, interface bundling, `datapath`/`full` views.
  2. Lay out with `elk_part`.
  3. Port only the pipeline-specific constraints (R1/R2 stage columns and lanes) into ELK as partition and port-order constraints, used when L1 finds pipeline registers.
- **Known issues, not fixed so that test stays clean:**
  - In `elk_r12`, bundles to interfaces are labelled by port id, which shows instance names instead of interface names (visible on the blind page).
  - `paper.py` overlaps on large designs.
  - The CPU's paper drawing got slightly busier than the first commit (329 vs 294 crossings), because the general control rule now draws some narrow data signals solid.

## Round 3 (v7): two grammars, one knob

What changed after the blind round (6 votes: 3 for `elk_r12`, 2 for `paper`, 1 for stage3's
ELK; crossings predicted only the first three) and the bend analysis (`paper` averaged 0.75
avoidable bends per two-pin net, ELK ~0; 28–40% of all bends sat on boundary-port nets):

1. **R13, generate-array folding** (`bridge.fold_arrays`): instances that differ only in a
   generate index are drawn once with "×N"; wiring helpers are remapped, invariants repaired
   (`_repair`). Both views benefit. `axil_crossbar_rd` under ELK: 22 → 1.7 crossings per net;
   `axis_ram_switch`: 29 → 0.7.
2. **System view** (`system.py`, RULES.md S1–S8): the grammar of SoC / accelerator figures —
   rectangles with bold names, teacher groups as titled containers, one labelled arrow per
   block pair, boundary ports grouped by teacher interface, a layered grid, verticals only in
   gaps, long arrows over a top channel, back edges along the bottom.
3. **Depth knob** (`bridge.build(root=...)`, `choose_view`): the grammar is chosen from the
   content of the level being drawn (pipeline registers or ≥3 mux/ALU/adder → datapath, else
   system); `root=<module>` draws that module's internals. `results/depth/` shows picosoc at
   the top (system), its UART (system, 4 units) and its CPU core (system, 9 units, busy).
4. Bend metrics in `svgmetric.py`: corners, avoidable corners on two-pin nets given the
   pins' facing, small jogs.

**v7, median crossings per bridge net** (overlap+through in brackets):

| Split | paper | elk_part | elk_r12 | **system** |
|---|---|---|---|---|
| dev (17) | 4.73 (9) | 3.00 (0) | 0.73 (0) | 0.59 (2) |
| **test (17, once)** | 2.45 (2) | 1.15 (0) | **0.37 (0)** | 0.46 (3) |
| **fresh (8, never seen)** | 2.66 (4) | 1.13 (0) | **0.62 (0)** | 0.95 (3) |
| CPU indicator | 4.23 (0) | 5.13 (0) | 3.16 (0) | 3.25 (3) |

Per category on test, `system` wins the hierarchical ones (cpu_hier 0.59 vs 2.06, network
0.42 vs 1.12, bus 0.11 vs 0.16) and loses the flat ones (cpu_flat 2.51 vs 1.57), where the
teacher's groups of one big module are densely interconnected and a single row of boxes is
the wrong shape. On the CPU indicator the datapath view (paper) is the right grammar; the
system view of a pipeline is correct but says nothing about stages.

`results/blind2_v7.html`: the second blind page, 8 fresh designs × {paper, elk_r12, system},
shuffled. Not yet scored.

**Open issues (v7):** flat big modules in the system view need a two-row grid; edge labels
("N sig") still collide on dense drawings; bundle labels to interfaces show the port id;
`rtllm_adder_pipe_64bit` still misses its teacher store entry; the system view's 2–3
residual overlaps are label-free stubs on the same row (tracked, not fixed, to keep test
clean). The contract will need a block count and a net label / interface name for the
system view; proposed via ADR, not added here.

## Round 4 (v8): figure check, second blind round, decisions

**Second blind round** (`results/blind_votes.md`): one reader, 8 fresh designs × {paper,
elk_r12, system}: **system 5, paper 2, elk_r12 1**. Crossings predicted the reader 3 of 8.
Both `paper` wins were small designs where it shows port names inside blocks.

**Figure check** (RULES.md, "checked against nine real figures"): neorv32, PULPissimo,
Cheshire (SoC); Gemmini, SUSpMV (accelerator); Ibex, CVA6, CV32E40P, 2LPE (core).
What did not hold: SoC figures are **bus-centred**, not flow-layered (3/3 and Gemmini): the
interconnect is a long bar, initiators below, targets above, short vertical arrows. Edge
labels carry interface names only; signal counts never appear. Containers are solid; dashed
means optional. Arrays are "0 … N-1" or a row of identical boxes.

**Decisions implemented in v8:**
- **S9 bus-centred layout** when a named hub (crossbar / interconnect / bus / decode / demux
  / switch) attaches to at least half the units with traffic both ways. Rows by the teacher's
  group kind (MEMORY / BUFFER / INTERFACE_ADAPTER / SERIALIZER / REGISTER_BANK / COUNTER_TIMER
  above, the rest below). Edges that would cut the bar go around through a side margin and
  enter the target from the far side. The renderer draws both layouts and keeps the one with
  fewer violations, then fewer crossings, so S9 can never regress a design.
- Edge labels only for single named signals and interfaces; "N sig" removed.
- Containers solid; folded arrays drawn as a stacked box with "×N".

On dev, S9 is chosen for `picorv32_picosoc` (the PULPissimo look, 16 crossings, 0 violations,
`results/picosoc_bus_v8.png`); every other design keeps the layered layout, so the dev / test
/ fresh numbers equal v7. The chooser is deliberately conservative; relaxing it needs a
readability score, not a crossing count.

**Still open:** flat big modules (cpu_flat) are the worst category for every renderer; the
datapath grammar should get the top-spanning control / register-file bars seen in CV32E40P
and Ibex; an interface used by one block could sit beside that block (Cheshire); the ADR for
block count and net interface name is still to be written.

## Round 5: the three open items, and what to optimise next

1. **ADR written**: `docs/adr/0003-diagram-multiplicity-and-net-labels.md` proposes three
   optional, backward-compatible fields — `Block.count`, `Net.label`, `Diagram.interfaces` —
   with the evidence from rounds 3–4. Nothing in `contracts/` was changed.
2. **Top-spanning bars (R14, CV32E40P / Ibex)** are implemented in `paper.py`
   (`render(..., bars=True)`, `mark_bars`) and **measured off**: on the CPU the look matches
   the figures, but with side ports the bars pull wires through themselves — through-block
   0 → 70, crossings 329 → 402. Bars need bottom-side ports with straight drops into the
   target's top entry; that is a router change, not a shape change. Off by default.
3. **Flat big modules (cpu_flat)**: tried the controller-as-bar hub (S10, `system.py`):
   `i2c_master` 196 → 186 crossings but 17 violations, `picorv32` worse; the chooser keeps
   the layered layout in every case. The figures suggest the right grammar for a flat core
   is the *datapath* one with bars (CV32E40P), so this item is blocked on the same router
   change as item 2. Recorded as the next engineering step, not patched around.

**Which metric predicts the reader?** Agreement between "pick the renderer with the lowest
metric" and the 14 blind votes (`results/blind_votes.md`), computed with `svgmetric.py`:

| metric | agrees | metric | agrees |
|---|---|---|---|
| crossings | 4 / 14 | wire length | 6 / 14 |
| bends | 6 / 14 | segments | 6 / 14 |
| labels crossed by wires (new) | 3 / 14 | label–label overlaps (new) | 3 / 14 |
| most labels | 4 / 14 | | |

No single number predicts a reader; compactness (length, segments, bends) does slightly
better than crossings. One reader and 14 votes is too little to fit anything.

**Optimisation directions, ranked by expected value over cost:**
1. **Router with top/bottom ports** (unblocks R14 bars, cpu_flat and the stacked-row system
   layout at once): verticals drop from a bar's bottom edge into the target's top entry, with
   the gap-track machinery reused for the horizontal legs.
2. **Votes at scale**: publish the blind page with vote capture (the artifact runtime can
   store per-viewer answers), get 5+ readers × 20 designs, then fit a 3–4 term readability
   score (violations, length, label hits, crossings) and use it as the chooser's objective
   instead of crossings.
3. **Importance-filtered views**: L1's 0–100 anchor score is already in the teacher output;
   dropping nets whose endpoints are all below 40 would give a "MEDIUM" diagram per design
   without new annotation. Measure: does it reduce crossings more than it loses labelled
   signals?
4. **Port names in the system view for small designs** (≤ 6 units): both `paper` wins in
   round 2 were this case. Cheap: reuse `paper`'s port labelling inside system boxes.
5. **Interface beside its block** (Cheshire): a boundary interface used by exactly one unit
   sits on that unit's outer side instead of the left/right column; removes most long
   boundary wires in bus layouts.
6. **Failure census on all 690 corpus designs**: the bridge has only been run on 36; a full
   pass (no drawing needed) would list the remaining front-end and store gaps
   (`rtllm_adder_pipe_64bit` is one).
7. **A second grammar for flat modules**: rows of units in a 2–3 row grid with an
   orthogonal router (the neorv32 peripheral grid) instead of one long row.

## Files
| File | Role |
|---|---|
| `rtl/rv32i_5stage/` | Our RV32I (MIT). Yosys sim self-check passes (result 56, 123). |
| `bridge.py` | L1 graph plus teacher store → `diagram.json`, `hints.json` and `meta.json` (kinds, labels, teacher groups and interfaces, pipeline lanes). |
| `paper.py` | Datapath-view renderer (RULES.md R1–R12). `bundle()` and `apply_view()` are the reusable transforms. |
| `system.py` | System-view renderer (RULES.md S1–S8). |
| `draw_l3.py` | stage3 e1 `draw()`, called directly; e1's `work()` uses SIGALRM, which Windows lacks. |
| `eval_set.py`, `evaluate.py`, `svgmetric.py`, `blind.py` | The evaluation. |
| `results/` | v1 dev; v6 and v7 dev/test/indicator; v7 fresh; both blind pages; `depth/` demo. |
| `out/` | CPU outputs. |

## Reproduce (repo root)
```
python pipeline/experiments/x1_l1_to_l3/eval_set.py
uv run --with nodejs-wheel python pipeline/experiments/x1_l1_to_l3/evaluate.py --version v6 --split dev
python pipeline/experiments/x1_l1_to_l3/blind.py v6
```
This needs the local corpus (`layers/l1_extract/data/corpus`, fetched by `scripts/fetch_corpus.py`) and the L1 Run Store (`layers/l1_extract/runs/store`); both are git-ignored. For the CPU, the top-module teacher prompt asked for one group per stage plus one for hazard/forward control. That instruction is beyond the protocol.
