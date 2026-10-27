# x4_fsm_timing: RTL -> FSM graphs and timing diagrams

**Owner:** pipeline  **Date:** 2026-10-24  **Branch:** `feat/fsm-timing`
**Plan:** [`docs/plan_fsm_timing.md`](../../../docs/plan_fsm_timing.md)  **Formats:** [`FORMATS.md`](FORMATS.md)

## Hypothesis
The block-diagram prototype (x1/x2 + e3) showed that L1's deterministic front end carries enough
structure to draw from. The same front end, without any generative model, is enough to draw
the two other diagram kinds of the proposal, and every element they draw is backed by a check:

- **FSM graph.** States are explored by executing the RTL, so the extracted state graph does
  not depend on coding style (case, one-hot, if-chains). Its names are the RTL constants. Every
  transition is cross-checked by Yosys (G1) and SymbiYosys proves that none is missing (G6).
- **Timing diagram.** Signals come from interface-protocol templates confirmed on the
  dependency graph, not from names. Every drawn value replays from a simulation (T1). Every
  causal arrow follows a real RTL dependency path with the right register count (T2). Idle
  stretches are compressed with exact cycle counts per clock domain (T3).

## Structure (the proposal's three stages)
| Stage | FSM | Timing | Where |
|---|---|---|---|
| 1 Extraction and analysis | L1 hybrid FSM engine + e8 (lines, encoding, one-hot names, counter-driven FSMs) | e9 pair-first protocol templates, clock domains, internal lanes | `layers/l1_extract/experiments/e8_fsm_extra`, `e9_protocol_templates` |
| 2 Abstraction and verification | `fsm_bridge` -> FsmGraph v0.1; G1 `fsm_yosys`, G2/G5 `fsm_check`, G3 semantic check, G6 `fsm_prove` (sby) | `tbgen`/`sim` (iverilog, Verilator fallback), `vcd`, `timing_bridge` (windows, gaps, arrows) -> TimingDiagram v0.1; T1-T3 `timing_check`, T4 determinism | here |
| 3 Drawing and layout | Graphviz dot + G4 SVG round-trip | WaveDrom + T5 SVG round-trip | `layers/l3_draw/experiments/e4_fsm_timing_draw` |

`x4_run.py` wires them; `block_tab.py` adds the existing block diagram (x1 bridge, x2 adapter,
e3 dot engine) so one page shows all three. `webui/serve.py` is the drop-RTL page.

## Measurement
- FSM: `manifest_fsm.json` holds 28 entries. It covers the 9 FSM designs of
  `e3_perturb_benchmark` as original, S1 and S2 rewrites, plus `picorv32_picosoc`. Gates G1
  to G6 as defined in plan §1 are recorded per FSM in `results.json`.
- Timing: `manifest_timing.json` holds 8 entries: sync_fifo, skidbuffer, axis_register, afifo
  (two clocks), uart_tx, cache_ctrl, uart_rx and axis_async_fifo (two clocks). Gates T1 to T5
  are recorded per diagram.

```
pipeline/experiments/x4_fsm_timing/install.sh                    # once: wavedrom-cli
uv run python pipeline/experiments/x4_fsm_timing/x4_tools.py --check
R="uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/x4_run.py"
$R --manifest pipeline/experiments/x4_fsm_timing/manifest_fsm.json --part fsm --prove \
   --out runs/x4_fsm_timing/fsm_set
$R --manifest pipeline/experiments/x4_fsm_timing/manifest_timing.json --part fsm,timing \
   --out runs/x4_fsm_timing/timing_set
$R --rtl layers/l1_extract/examples/rtl/uart_tx.sv --part block,fsm,timing   # any RTL
uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/webui/serve.py --port 8765
```
Each run writes `results.json`, `stages.json`, `rejected.json` and a self-contained
`gallery.html` under `--out`. Its per-design files are listed in FORMATS.md.

## Pass / abandon criteria
Decided before running, from plan §5 (M1, M2a, M2b, M3, M4 sby part):
- **FSM.**
  - G4 round-trip and G2 structure hold on 100% of FSMs whose semantic check is consistent,
    consistent-subset or semantic-only.
  - At least 4 one-hot FSMs are drawn with RTL state names, and 0 are rejected for coding style.
  - G5 isomorphism holds across orig/S1/S2 on 9 of 9 designs.
  - G1 agrees on every FSM that Yosys parses after forcing.
  - G6 reaches proven or bounded(20) on at least 80% of FSMs.
- **Timing.**
  - At least one window per confirmed interface on 7 of 8 designs.
  - T1, T2 and T3 hold at 100%. T4 gives identical hashes on 8 of 8 designs. T5 renders 8 of 8.
  - The two-clock designs show two domain groups and no solid cross-domain arrow.
  - Skidbuffer gives exactly its two structural interfaces.
- **Web tool.** All three tabs appear in under 60 s for uart_tx and for the wb2axip folder with
  top skidbuffer. rr_arbiter gets a friendly "nothing to draw" page. Nothing is written outside
  `runs/`.
- **Abandon or redesign.** Redesign the arrow derivation if T2 stays under 90% after two rounds.
  Fall back to name pairing with an "unconfirmed" badge if templates confirm under 80% of
  hand-labelled pairs.

## Results

### Rounds
| Round | Trigger | Change | Result |
|---|---|---|---|
| R1 timing (`runs/x4_fsm_timing/timing_r1`) | first end-to-end run | none | 8/8 designs, 39 diagrams, T1-T5 39/39; afifo drew 17-18 cdc arrows; clock period shown in raw ps |
| R1 FSM (`fsm_r1`) | first end-to-end run with `--prove` | none | 30 FSMs, 28 drawn; G6 proven 21, failed(edge) 5; G5 5/9 designs |
| R2 FSM (`fsm_r2`, `fsm_r2b`) | the 5 failed(edge) were one-hot rewrites whose executed graph missed a counter-gated exit (e.g. uart_tx S1 `PH_PAY -> PH_TAIL` needs `&nb`) | proof-guided repair: edges from an sby counterexample from reset are added (`seen_by: proof`, guard `?`), unconditional guards out of the same state demoted, re-prove + re-run Yosys. Syntactic/executed mismatch: rebuild from the executed graph, reset from `fsm_semantic.analyze`, keep only if proven | all 5 repaired graphs proven and Yosys `agree`; fsm_hdlc S1 recovered |
| R2 timing | R1 observations | cdc arrows only from registers, one per lane pair (repeats logged); timescale carried into the diagram (`T=10 ns`); FSM state lanes named from fsm_ext | afifo 9 arrows |
| R3 (`fsm_r3`, `timing_r3`) | full rerun after all component fixes | none | tables below |

### R3 FSM (`manifest_fsm.json`, 28 entries, `--prove`)
| Gate | Result |
|---|---|
| FSMs found / drawn / rejected | 30 / 29 / 1 (`spimemio.state`: L1 semantic engine unsupported construct) |
| G2 structure, G4 SVG round-trip | 29/29, 29/29 |
| G3 semantic | all drawn FSMs consistent, consistent-subset or semantic-only |
| G5 same graph across orig/S1/S2 | **9/9 designs** |
| G6 SymbiYosys completeness | **proven 29/29** (5 after proof-guided repair) |
| G1 Yosys `fsm_extract` | agree 21, yosys_declined 7, disagree 1 |
| Encodings drawn with RTL state names | binary 16, one-hot 10, enum 3 |
| picorv32_picosoc wall time | 256 s (L1 semantic budget + e8 replay + 3 proofs) |

G1 `disagree` is picorv32 `cpu_state`. L1 has 6 edges out of `cpu_state_ld_rs2` and
`cpu_state_shift` that Yosys's `fsm_extract` does not list. The proof still holds, because
those edges are allowed, not required. The cover pass leaves them unreached at depth 20 from
the instance, so they are probably parameter-disabled paths. They need a top-level cover
before they are trusted (open item).

### R3 timing (`manifest_timing.json`, 8 designs, `--part fsm,timing --prove`)
| Gate | Result |
|---|---|
| Designs with diagrams | 8/8 (46 diagrams) |
| T1 replay, T2 arrow paths, T3 cycle accounting, T4 determinism (two runs, same VCD sha256), T5 SVG round-trip | 46/46 each |
| Simulator | iverilog 7, Verilator 1 (uart_tx: iverilog `sorry:` on constant selects) |
| Two-clock diagrams | afifo: 2 domain groups (10 ns / 14 ns), cdc arrows dashed orange, none solid |
| Caps | max 12 lanes; arrows split at 6 per time point (cache_ctrl FSM window: 22 arrows over its span) |
| Skidbuffer | exactly 2 VALID_READY interfaces (`i_valid/o_ready/i_data`, `o_valid/i_ready/o_data`), despite L1's prefix bundles |

### Web tool (M3)
| Input | Time | Result |
|---|---|---|
| `examples/rtl/uart_tx.sv` | 22 s | Block + FSM (proven) + 9 timing diagrams |
| `data/rtl/wb2axip/rtl/` folder (62 files), top `skidbuffer` | 4 s | Block + 6 timing diagrams, no FSM |
| `examples/rtl/rr_arbiter.sv` | 14 s | Block + 3 timing diagrams: e9 confirms `req_i -> gnt_q -> gnt_o` as REQ_ACK, so the plan's "negative" expectation was wrong |
| VerilogEval `Prob022_mux2to1` (combinational) | 2 s | Block; FSM and timing say "nothing to draw", no traceback |

Done check (2026-10-24): `uv run ruff check .` reports only the 5 pre-existing E501 in the
untracked `docs/report/gen_flow.py`. `uv run pytest` gives 46 passed, 2 skipped.

## Conclusion
Keep. All three proposal stages run end to end without a generative model. Every FSM drawn
is proven complete by SymbiYosys. Every timing diagram replays from simulation, and every
arrow follows an RTL dependency path. Two plan assumptions changed:

- The completeness proof also repairs the graph. Sampling-based execution misses
  counter-gated exits, and the proof adds them back.
- An arbiter's request/grant pair is a legitimate timing subject.

Open items: the plan's M4 items not done here (ELK engine and blind vote for FSMs, the
mismatch triage over teacher-v1), M5 (sby cover traces as stimulus, existing-testbench runs on
the corpus, rename measurement), and ADR gates A and B. Promoting FsmGraph/TimingDiagram into
`contracts/` needs the ADR, and nothing in `contracts/` or any `src/` was changed.
