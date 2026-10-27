# Changelog

## stage1-spec-v1.7 (2026-10-03)
- Frontend (found by round-4 annotators, each with a regression test):
  - slang silently turns a whole always block into an InvalidStatement when a branch that is dead
    under the current parameters is illegal; dataflow (incl. resets, trailing `if (rst)`) is now
    recovered from the syntax tree.
  - False resets removed: structural sync-reset guesses that are also data; reset-named signals
    driven by ordinary logic; reset status leaking through `.rst(a || b)` port expressions; and
    every signal of `if (!rst || !valid)` becoming a reset. AXI `ARESETn` recognized.
  - Default `--timescale` (mixed-timescale repos).
- importance-score-v2: refitted on 9,151 anchors / 412 modules (grouped CV AUC MEDIUM 0.82 /
  HIGH 0.87); knots raw 60.4 -> 70, 32.8 -> 40.
- Data: round-4 corpora (386 designs), 683 Opus-level session units in total, rename augmentation
  (e7), export-sft dedup + split by original module (`--augment`, `--split-dir`), train_lora
  `--eval-data`.

## stage1-spec-v1.6 (2026-10-03)
- Quantified importance (SPEC §4.6, `importance.py`): every anchor gets `score` and `struct_score`
  (0-100) from 17 name-free structural features + role (+ tier for `score`). Coefficients fitted
  on 1,735 teacher anchors (grouped CV AUC MEDIUM 0.84 / HIGH 0.91) and frozen.
- `Controls.importance` = score (default) | tier | structure, `min_score`; CLI `--importance`,
  `--min-score`. Thresholds HIGH >= 70, MEDIUM >= 40 for every mode.
- Weak-annotator study (experiments/e6, Claude Haiku 4.5): 54/54 units pass the validator; the
  `structure` mode closes most of the importance gap to an Opus-level annotator.
- Scores are computed after annotation: prompts and Run Store keys unchanged.

## stage1-spec-v1.5 (2026-10-02)
- Semantic FSM extraction by executing the RTL (fsm_semantic.py) + hybrid output with
  `semantic_check`; 18/18 FSMs preserved across equivalence-checked messy rewrites (syntactic: 0/18).
- Evidence lines on every anchor (`anchor-v2.1`, validator E_EVIDENCE).
- Optional multi-pass self-audit (`--passes`, `--use-round`); measured to give no consistency gain,
  default stays 1.
- Perturbation benchmark tooling: scripts/equiv_check.py (strict reset BMC), perturb_equiv.py,
  perturb_compare.py (FSM isomorphism, physical-signal anchor matching).
- New corpora: verilog-axis, verilog-uart, serv, darkriscv (+ include staging fix).
- FSM candidates must be decoded as a whole value; validator accepts child-output wires for
  FSM_STATE/STORAGE; check_answer.py works on pass files.

## stage1-spec-v1.4 (2026-10-02)
- `--target block|fsm|timing` (default block). Target only selects outputs; annotation/caching unchanged.
- Deterministic FSM extraction (`frontend/fsm.py`): states, reset, guarded transitions, Moore/Mealy
  outputs, parameter-constant folding; Mermaid + Graphviz output. 44/44 FSMs pass structural checks.
- `timing` is a placeholder that lists handshake interfaces for the future formal-trace flow.

## stage1-spec-v1.3 (2026-10-01) — after session-annotation round 1 (63 modules)
- roles-v2: + STATUS, COMMAND, INDEX, HOLDING_REG, DECODE, CLOCK_GEN; tighter CONTROL_FLAG /
  PIPELINE_REG / INTERFACE_ADDR definitions; 7 tie-break rules in the prompt (`anchor-v2.0`).
- Frontend: sync resets detected at any nesting depth; extra edge signals named like resets are
  resets; FSM candidates exclude counters (x <= x +/- k) and accept 1-bit FSMs with an explicit
  next-state variable; `x ? S1 : S0` counts as a constant assignment.
- Modules with an FSM candidate are never "trivial" (always go to the teacher).
- Privileged spec tells submodules that the spec describes the whole design.
- Validator: W_STORAGE_SHAPE only for combinational STORAGE (shift registers of any width are fine).

## stage1-spec-v1.2 (2026-10-01)
- Teacher always annotates at full detail (LOW); levels become deterministic views by importance
  (§4.4). New user Controls (§4.5). Prompt `anchor-v1.1`.
- Teacher may receive a privileged natural-language design spec; it is excluded from the
  student input and SFT samples.
- Session annotation path: `batch plan --units-dir` + `batch ingest-session` + `--store-only`
  (annotations written by a Claude session instead of the API, recorded as model `claude-session`).

## stage1-spec-v1.1 (2026-10-01)
- §6 trace engine: BFS slicing replaced by cost-bounded Dijkstra + relevance score with
  per-level thresholds; control-cone dilution; closure restricted to anchors; top ports are
  boundary nodes, not Steiner terminals. Reason: picorv32 reduction was 0.19 with BFS.
- §3 entity IDs: tie-break by character offset (not name) so renaming never permutes IDs
  when several signals are declared on one line.

## stage1-spec-v1.0 (2026-10-01)
- Initial frozen spec: roles-v1, entities-v1, runstore-v1, anchors-v1.
