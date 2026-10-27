# e8_fsm_extra

**Owner:** L1　**Date:** 2026-10-24

Sidecar enrichment of L1 FSMs for the x4 FSM-graph prototype (plan `docs/plan_fsm_timing.md`
§2 Stage 1, M1 and M4). `fsm.json` and the frozen SPEC are untouched; output is
`runs/e8_fsm_extra/<name>/fsm_ext.json` in the format of
`pipeline/experiments/x4_fsm_timing/FORMATS.md` (one element per FSM = `FSM.to_json()` + `extra`).

```bash
uv run --package rtl2d-l1 python layers/l1_extract/experiments/e8_fsm_extra/e8_extract.py \
    --files layers/l1_extract/examples/rtl/uart_tx.sv --top uart_tx \
    [--counters] [--out runs/e8_fsm_extra/uart_tx] [-I DIR] [-D DEF] [--time-budget S] [--no-replay]
```

Library (x4 loads the file with `importlib`, siblings load themselves the same way):
`enrich(run, *, counters=False, seed=None, time_budget=None, report=None, replay=True)`.

| file | content |
|---|---|
| `e8_extract.py` | `enrich`, CLI, replay of `fsm_semantic.detect` (seed/budget/`budget_exhausted`), renaming, `extra` assembly |
| `lines.py` | `LineWalker` = subclass of `fsm._Extractor` (L1's own `stmt`/`assign` visitors) recording `{file,line}`; extended mode (one-hot bit tests, port aliases, next-state logic in submodules, `s <= s +/- k`, guard evaluation per state); bit-index / bit-tap / macro naming tables |
| `states.py` | values, encoding, unnamed detection, `fsm.py` Moore/Mealy output rule |
| `candidates.py` | counter-driven FSMs (`--counters`, rules R1-R6), guards of counter edges |
| `sweep.py` | M4 sweep: counter admissions over the 262-design corpus, literal plan rule vs R1-R6 |

## Hypothesis
1. Source lines, values, encoding and RTL state names can be attached to every L1 FSM without
   changing L1 `src`, by re-walking the slang AST with L1's own visitors.
2. One-hot rewrites get RTL names (enum/parameter, bit-index constants `s[IDLE]`, bit taps
   `assign hot_i = w[0]`, `` `define `` codes) instead of `S_<v>` or wrong equal-value names.
3. A relaxed candidate rule admits counter-driven controllers (`simpleuart.recv_state`,
   verilog-uart `uart_rx.bit_cnt`, its e3 rewrites) but not plain counters / pointers / CSRs.

## Measurement
- The 27 non-picosoc entries of `pipeline/experiments/x4_fsm_timing/manifest_fsm.json`, the
  examples `uart_tx, cache_ctrl, sync_fifo, rr_arbiter`, and `picorv32_picosoc` once.
- Per FSM: encoding, `unnamed` count, edges with `transition_lines` / all edges, `reset_line`,
  `reached`, simplifications; L1-vs-walker divergence is logged as a simplification.
- Counters: decision table over the positives (simpleuart, verilog-uart `uart_rx`, e3
  `uart_rx` S1/S2) and negatives (sync_fifo pointers, `axil_register_rd`, VerilogEval counters,
  verilog-axi `axil_reg_if`/`axi_register`, `biriscv_csr`, every counter in the manifest).

## Pass / abandon criteria
From the plan (M1/M4, §6):
- M1: >= 4 one-hot FSMs with RTL state names, 0 rejected for coding style; every edge of a
  syntactic FSM gets source lines; values/encoding for every FSM.
- M4: `simpleuart.recv_state`, `spimemio.state`, e3 `uart_rx.ph` extracted with cycle-count or
  recovered guards; CSR negatives 0 extracted; new false positives <= 2 on the 262-design sweep
  (`sweep.py`).
- Abandon (§6): if the counter relaxation cannot stay <= 2 FP after two rounds, keep today's rule
  and require a `case` on the register.

## Results

### R1 (2026-10-24): FSM enrichment, 27 manifest entries + examples (heuristic L1)
- 27/27 FSMs: values known for all, **0 unnamed states**, `reset_line` found 27/27, `reached`
  27/27; encodings 9 onehot, 15 binary, 3 enum. 0 walker divergences from L1 on the 13
  syntactic FSMs (lines on 112/112 edges). Semantic-only FSMs (14): lines on 95/125 edges; all
  30 unlined edges are hold self-loops (no assignment exists). 2 FSMs whose next state is
  bit-wise (S1_fsm_ps2data, S1_reservoir) get lines approximated by all non-reset assignments
  to the register, recorded as a simplification.
- One-hot designs (encoding / names):

| design | register | encoding | names | how |
|---|---|---|---|---|
| S1_fsm_ps2data | `oh` | onehot | HUNT, MID0, MID1, FIN | bit-index `oh[HUNT]`; L1 had MID0, MID1, S_4, S_8 (MID0=1 was an equal-value accident) |
| S2_fsm_ps2data | `fsm_i.hot` | onehot | H_SEEK, H_B2, H_B3, H_FIN | localparams (L1) |
| S1_lemmings2 | `mv` | onehot | DROP_W, TRK_W, DROP_E, TRK_E | localparams (L1) |
| S2_traffic_light | `lamp_sel` | onehot | PH_GO, PH_WARN, PH_STOP, PH_OFF | localparams (L1) |
| S1_uart_tx / S2_uart_tx | `ph` / `phase_r` | onehot | PH_* | localparams (L1) |
| S1_ugly_mul | `st` | onehot | HOLD, SPIN, FIN | localparams (L1) |
| S2_ugly_mul | `w` | onehot | hot_i, hot_r, hot_f | bit taps `assign hot_i = w[0]` (L1: S_1, S_2, S_4) |
| orig_sequence_detector | `curr_state` | onehot | IDLE, S1..S4 | parameters |
| S2_sequence_detector | `ph_r` | binary (sparse 0,3,5,6,7) | P_TRI, Q_INIT, P_TWO, P_ONE, Q_MATCH | P_* from submodule `sd_route` (L1: S_0, S_5, S_6) |
| S1_sequence_detector | `pos` | binary | SQD_A..SQD_E | `` `define `` codes via the SourceManager (L1: "5", "2", ...) |
| S2_fsm_hdlc | `run_st` | binary | HD_* | `` `define `` codes (L1: S_0..S_14) |
| picosoc | `cpu.cpu_state` | onehot | cpu_state_* | localparams; reached 4/8 (consistent-subset) |

  Every rename is in `extra.simplifications` with the line of the naming evidence.

### R1: counter-driven FSMs (`--counters`)

| register | expected | result | reason / guards |
|---|---|---|---|
| simpleuart `recv_state` | + | ADMIT | 11 states; all 11 non-self guards recovered from RTL (`!ser_rx`, `2*recv_divcnt > cfg_divider`, `recv_divcnt > cfg_divider`) |
| simpleuart `send_bitcnt` | (not listed) | ADMIT | TX bit sequencer (load 10/15, count down); guards recovered |
| verilog-uart `uart_rx.bit_cnt` | + | ADMIT | 11 states, 12 edges, e.g. `S_10->S_9: !(prescale_reg > 0) && !rxd_reg` |
| e3 S1 `uart_rx.ph` / S2 `uart_rx.phase_k` | + | ADMIT | both isomorphic to the original (networkx, reset-matched) |
| spimemio `state` | + | not a counter case | already an L1 FSM (`unsupported` by the semantic engine, 13 literal-named states); the counter path does not apply |
| sync_fifo `wptr_q`, `rptr_q` | - | reject | R5 (flush edges = global target; `+1` under `!flush_i && do_push` everywhere) |
| sync_fifo `count_q` | - | reject | R4 avg out-degree 3.56 |
| verilog-axi `axil_register_rd`, `axi_register`, `axil_reg_if` | - | 0 candidates | no `x <= x +/- k` register <= 8 bits (`axil_reg_if` has 2 L1 semantic-only `timeout_count_reg` FSMs, not from e8) |
| `biriscv_csr` | - | 0 candidates | |
| uart_tx `baud_cnt_q`, `bit_idx_q`; e3 S1/S2 `nb`, `tmr`, `nib`, `tally`, ugly_mul `k`, `ctr`, `lap` | - | reject | R5 |
| traffic_light `cnt`/`tmr`/`ticks` | - | reject | R2 (> 48 values) |
| VerilogEval count1to10, count10, count15, countslow | - | reject | R5 (wrap and inactive reset normalised) |
| VerilogEval count1k, countbcd, timer | - | reject | R1 (width) |
| VerilogEval shiftcount | - | reject | R4 |
| VerilogEval counter_2bc `state` | - (?) | ADMIT | 2-bit saturating up/down predictor; boundary states differ. Debatable (VerilogEval files it as an FSM and the register is named `state`); counted as 1 FP |
| picosoc `mul_counter` / `pcpi_timeout_counter` / `reg_sh` / `dummy_count` | - | reject | R2 / R5 / R3 / R3 |

Positives 4/4 counter cases admitted with recovered guards; CSR/register negatives 0; known FP 1
(`counter_2bc`). The 262-design sweep is still open (M4 `sweep.py`).

### Timing (WSL, heuristic)
Small designs: e8 0.1-3 s. picorv32_picosoc: L1 83 s + e8 110 s with `--counters` (replayed
detect loop ~72 s, `budget_exhausted=true`; counter analysis ~30 s). `--no-replay` skips the
replay (reached from one `analyze()` per FSM, `budget_exhausted=null`).

### R2 (2026-10-24): review fixes
Re-run on the same designs after an independent review. Commands: the CLI above per design;
manifest driver over the 27 non-picosoc entries (outputs `runs/e8_fsm_extra/<name>/`);
`sweep.py` over `examples/corpus.json` + `data/corpus/{rtllm,verilog_eval,picorv32,opensource}.json`
(`runs/e8_fsm_extra/sweep/sweep.json`).

What changed:
- **Counter edge labels**: sampled QM cubes are no longer used as labels (they contradicted the
  RTL, e.g. verilog-uart `S_10->S_10 [rxd_reg]` while the RTL holds on `prescale_reg > 0`). A
  label is the recovered syntactic condition; a hold self-loop gets `!(exit_1 || ...)` when
  every write to the register is a recorded constant / `+-k` assignment (logged as a
  simplification); otherwise `<datapath condition>`. Result: `uart_rx.bit_cnt` holds are
  `prescale_reg > 0` (S_1..S_10) and `prescale_reg > 0 || rxd_reg` (S_0); simpleuart
  `send_bitcnt` S_7 hold `!(send_divcnt > cfg_divider)`; e3 S1 `ph` S_10 hold `!step`.
  All 5 positives: 0 `<datapath condition>` edges.
- **Guard evaluation** is three-valued with net definitions inlined (`wire park = !(tk_live ||
  ph_live)` is false whenever `ph != 0`), so records that cannot fire in a state are dropped
  (e3 S1 `S_10->S_10` no longer `!step && park && !smp`; e3 S2 `S_1->S_0` is `t_go`).
- **`*` lines per state**: in exact mode the walker now also tracks the enclosing `if`/`?:`
  guards (same branch logic as fsm.py); a `*` record is listed under `S->D` only if it can fire
  in S, and not when a later statement of the block surely overwrites it (`definite()` over
  if/case). Fixed e.g. S1_traffic_light `BOOT->STOP [32]` (was [32, 36]), S1_fsm_hdlc
  `R0->R1 [40]` (was [40, 46]), `R6->R0` none (was [28, 31, 39]), S2_sequence_detector
  `P_TRI->Q_INIT [18]` (the always-overwritten default line 14 dropped). Pruned pairs are
  counted in a simplification; `*->D` keeps every line.
- **Extended mode**: `default:` of `case (1'b1)` applies only when no tested bit is set
  (synthetic `ohzero.sv`: `WAIT->IDLE [10]`, was [10, 11]); bit-wise next state (`oh[K] <= ...`)
  also gives hold self-loops the all-writes fallback (S1_fsm_ps2data 6/6, S1_reservoir 16/16).
- **reset_line** fallback when no reset state is known: first constant assignment under a
  condition naming a RESET-edge signal (spimemio `state` -> line 212, logged).
- **Counter rule** (sweep-driven, see table): R6 added (every non-reset write is a constant or
  `+-k`; rejects shift-in / data loads such as VerilogEval fancytimer `scount`); R5 now ignores
  constant assignments that can fire in every state (global loads, also when the parent ties
  `flush_i` to 0: soc_top fifo pointers), compares only maximal per-state sets (boundary states
  of saturating up/down counters: `counter_2bc`, soc_top `count_q`) and, when all states have
  the same moves, leaves the wrap state's terminal-count guard out (RTLLM `accu.count`).

Manifest (27 FSMs): values known 27/27, 0 unnamed, reset_line 27/27, reached 27/27; encodings
9 onehot / 15 binary / 3 enum (unchanged); 13 syntactic FSMs 112/112 edges lined, 0 walker
divergences; 14 semantic-only 102/125 lined (was 95/125), the 23 unlined are hold self-loops.

Counter table (`--counters`):

| register | expected | result | guards |
|---|---|---|---|
| simpleuart `recv_state` | + | ADMIT | 11 syntactic + 11 derived holds, 0 datapath |
| simpleuart `send_bitcnt` | (not listed) | ADMIT | 17 syntactic + 16 derived, 0 datapath |
| verilog-uart `uart_rx.bit_cnt` | + | ADMIT | 12 + 11, 0 datapath |
| e3 S1 `uart_rx.ph` / S2 `uart_rx.phase_k` | + | ADMIT | 12 + 11 each, 0 datapath |
| sync_fifo `wptr_q`/`rptr_q` / `count_q` | - | reject | R5 / R4 |
| `axil_register_rd`, `axi_register`, `axil_reg_if`, `biriscv_csr` | - | 0 extracted | |
| VerilogEval count1to10, count10, count15, countslow | - | reject | R5 |
| VerilogEval count1k, countbcd, timer / shiftcount | - | reject | R1 / R4 |
| VerilogEval `counter_2bc` | - | reject (was ADMIT) | R5 saturating counter |
| synthetic `seq.sv` (case on step, `step+1`) / `mod10` / `updown` | + / - / - | ADMIT / reject / reject | |

Sweep, 262 designs (231 s; 1 timeout at 180 s: verilog-axis `axis_ram_switch`; picosoc is
not in these manifests): 108 `x <= x + k` candidate registers; today's L1 rule admits 0; the
literal plan rule (R1-R4 + "relative successors not the same everywhere") admits **35**; R1-R6
admits **2**, both verilog-uart `uart_rx.bit_cnt` (in `uart` and `uart_rx`; listed positive).
New false positives on the sweep: **0** (criterion <= 2). Literal-rule admissions are mod-N
counters, dividers, fifo pointers/counts, bit indices and timers (the R5 reason of each is in
`sweep.json`). Rejections: R5 45, R1 22, R2 18, R6 10, R3 9, R4 2.
Not admitted and arguably FSM-like: verilog-uart `uart_tx.bit_cnt` (one load + count-down,
same move under one guard everywhere).

picorv32_picosoc (run once, `--counters`): L1 74 s + e8 61 s. 4 FSMs: `cpu.mem_state`
(binary, literal names), `cpu.cpu_state` (onehot, `cpu_state_*`, 26/26 lined),
`spimemio.state` (unsupported, 17/17 lined, reset_line 212 via the reset-port fallback),
`simpleuart.recv_state` (e8-counter, reset_line 68). Counters: `recv_state` ADMIT;
`send_bitcnt` **reject** here (R5) although admitted standalone: inside picosoc the semantic
engine never drives `reg_dat_we`, so the `0 -> 10` load edge is not reached and the only moves
left are the `0 -> 15` wrap-like load and `-1` (same as verilog-uart `uart_tx.bit_cnt`). R5 is
computed on the edges `analyze()` reaches, so it depends on the elaboration context.
`mul_counter` R2, `pcpi_timeout_counter` R5, `reg_sh` / `dummy_count` R3.

## Conclusion
Keep experiment-local until ADR gate A. Hypotheses 1 and 2 hold on the manifest. Hypothesis 3
holds on the listed positives/negatives and on the 262-design sweep (0 new FP) with R1-R6;
the literal rule ("relative successor not the same everywhere") admits 35 sweep registers, so
it must not be promoted as written. R5 depends on recovered guard text, so it is sensitive to
how conditions are written (two textually different but equivalent guards count as different);
the sweep is the guard against that. Open: `spimemio.state` (L1 `unsupported`, not a counter
case), cycle-count guards (`guards.py`, M4).
