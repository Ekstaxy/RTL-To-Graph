# Messy-but-equivalent rewrite rules (perturbation benchmark)

Goal: produce RTL that a human would call "the same circuit written by someone else, badly",
so we can test whether Stage 1 extracts the same architecture information.

## Hard constraints (the equivalence checker enforces them)
1. Same top module name, same parameters (names and defaults), same port list: names, directions,
   widths, order.
2. Cycle-identical behavior from reset: for every input sequence, every output is equal in every
   cycle (checked with `scripts/equiv_check.py`, SAT-based BMC from reset).
3. Must elaborate cleanly with slang: `python -m rtl2d_l1.cli entities FILES --top TOP` shows no
   elaboration errors.
4. Must be readable by Yosys 0.33 (`read_verilog -sv`): plain Verilog-2005 / simple SystemVerilog
   (logic, always_ff/always_comb, typedef enum are fine; no interfaces, no unpacked port arrays,
   no packages, no classes).

## What MUST change
- Every internal (non-port) signal gets a new name (no copy of the old name, no obvious synonym
  like state_q -> state_r; pick neutral or misleading-but-plausible names).
- No comments that explain intent.
- If the design has an FSM: change its coding style (one-process <-> two-process, case <-> if/else
  chain) AND its state names AND its encoding (binary <-> one-hot <-> gray, or different values).
- Apply at least 5 techniques from the style list.

## Style S1: messy-flat (stay in one module)
- split one always block into several / merge several into one
- case <-> if-else chain; ternary <-> if; nested conditions flattened with && / ||
- intermediate wires for sub-expressions; De Morgan rewrites; redundant-but-harmless logic
  (e.g. `x & 1'b1`, double negation, duplicated registers that are never read)
- reorder declarations and blocks; Verilog-2001 <-> SV keywords; packed concatenations
- enum <-> localparam/`define encodings; arithmetic rewritten (x+1 as x - ~0 etc. only if same width)

## Style S2: messy-hierarchical
- everything in S1 is allowed, PLUS
- move at least one functional part (counter, datapath, next-state logic, storage, output
  decoder) into a NEW submodule (same file), connected by ports; optionally wrap the logic in an
  inner module and make the top a thin wrapper with the original ports
- use a function or a generate loop somewhere if it fits

## Deliverables per rewrite (data/perturb/<design>/<S1|S2>/)
- the rewritten source file(s)
- mapping.json:
  {"signals": {"<orig internal name>": "<new name or null if eliminated/merged>"},
   "states": {"<orig state name>": "<new state name or null>"},
   "moved_to_submodule": {"<orig internal name>": "<submodule instance path>"},
   "techniques": ["..."], "equiv": "<checker output line>"}
