# x5: proof-carrying state graphs

x4 extracts a state graph with heuristics, checks it, and rejects it when a check fails. x5 turns
that around: the proof engine computes the graph, and every element of the picture carries the
evidence for it. A proposer (the L1 extractor, a person, an LLM) only chooses what to look at and
what to call things. A bad proposal can make the picture ugly; it cannot make it wrong.

## What a certificate claims

`prove.py` projects the design's transition system onto an observation: any vector of signals of
one module (a state register, several registers together, predicate wires). `cert.json`
(`proven-graph-0.1`) then states, under the assumptions it lists:

| element | claim | evidence |
|---|---|---|
| `witnessed` edge A -> B | happens in a real execution from reset | an input trace; Icarus Verilog shows the pair at the stated step |
| `witnessed`, `needs_power_up` | happens from reset when the design powers up in the state the trace lists | the trace carries register and memory values; the simulator is given them only where the RTL leaves the bits unknown |
| absent edge | can never happen | closure of one-step successors from arbitrary states (`completeness.k = 0`), or k-induction |
| `undetermined` edge | may or may not happen | one-step possible from some state nobody proved reachable; drawn dashed, never as fact |
| `model-witness` edge | the model has a trace the simulator does not reproduce | kept apart; means the two tools disagree or the trace depends on an unknown value |
| state name | the RTL expression of that name equals the value | compiled into the module and proven equal (`post.py: verify_names`) |
| guard label | the edge is taken exactly when the label holds | truth table over the proposed atoms, enumerated by the solver (`guards.py: guard_tables`) |
| drawing | shows the certificate's nodes and edges, no more, no less | the SVG is parsed back and compared (`post.py`) |

Assumptions are part of the certificate: one clock; reset held `reset_cycles` cycles and never
reasserted; inputs unconstrained; unknown (`x`) values may be anything; power-up values are the
RTL initial values and otherwise anything. `scope` says which module the proof is about: a
module-level proof holds in every design that instantiates the module with those parameters
(its edge set is an upper bound there), but its witnesses are executions of the module alone.

Refusals instead of guesses: latches, several clock nets, both clock edges, black boxes, more
than 64 observed states. `Refuse` produces no graph.

## Algorithm

1. Model: `read_verilog; hierarchy; prep -flatten; async2sync; dffunmap; setundef -anyseq;
   write_smt2`. Unknown values become free inputs, so the model has at least the behaviours of
   the hardware.
2. Entry states: every observation possible in the first cycle after reset (all-SAT).
3. Upper bound: successors of each observation from an arbitrary state, closed from the entry
   states. The real state is one of the arbitrary ones, so no real transition is missing, at any
   depth. If the closure exceeds the state limit, BMC plus k-induction is used instead.
4. Lower bound: (a) random simulation in Icarus Verilog with eight stimulus styles per input:
   every pair it shows is real, and a pair outside the upper bound means Yosys and the simulator
   disagree, which refutes the certificate; (b) BMC from reset; (c) snapshot relay, below; (d) BMC
   continued from the end of a trace already found, with that trace's inputs pinned, window by
   window.
5. Gap: closure edges without a witness are `undetermined`; k-induction over the witnessed graph
   removes those it can prove unreachable.
6. Replay: every trace used as a witness is simulated again, first from its inputs alone. Only a
   trace that fails that way is replayed with its power-up state, and its edges say so.
7. Same design: the simulator reads the files in the order the model was built from, with macros
   carried from file to file as Yosys does (no `iverilog -u`), SYNTHESIS and YOSYS defined. Every
   named register and memory of the model must then exist in the simulator under the same
   hierarchical name (`same_design`). picosoc is why: its top file `define`s the register file
   picorv32 uses, so read in another order, or one file at a time, it is another design, and
   replays agreed only by luck.

### Snapshot relay (`relay_phase`)

BMC from reset is exact but shallow; simulation is deep but blind. The relay joins them. The
simulator is run again over a prefix of one of its own runs and dumps every named register and
small memory at a chosen cycle. The solver starts from exactly that state and looks 1, 4, 12
cycles ahead for an edge still without a witness. The prefix plus the solver's continuation is
then replayed from reset with inputs only, and kept only if the simulator reproduces every
observation. Nothing in between is trusted: registers the snapshot could not read are free in the
solver, and a continuation that relied on them fails the replay and is dropped. The end of every
new trace is a snapshot point of the next round, so states no simulation reached get explored.
Edges whose only BMC trace needs a chosen power-up state are searched again the same way, because
a trace from reset is better evidence.

### Auxiliary observation and projection (`aux`, `project`)

The closure works on what is observed. A counter observed alone looks as if it could step from
any value, because "any state with cnt = 5" includes states the machine driving it never
reaches. Observe the counter together with that machine (`aux` in a proposal) and the closure is
taken over the pairs; the pairs that cannot occur drop out. `project()` then drops the auxiliary
signals again: an edge of the result exists iff some edge of the product projects onto it, is
witnessed iff one of those is. The product edge set stays in the certificate as
`completeness.support`. It is not trusted either: `check.py` proves the support set by
induction and recomputes the projection itself. Projection is the same operation as folding
states into classes, so it is also the basis for readable abstractions of a proven graph.

## Independent checker

`check.py` does not import z3 and shares no encoding with `prove.py`. From the RTL and a
certificate it (1) simulates the traces again, and (2) writes the edge set as a Verilog monitor
and lets Yosys's own SAT pass (MiniSat) prove it by temporal induction, the reset protocol being
part of the property. Two solvers and two encodings must agree on completeness; two front ends
(Yosys, Icarus) must agree on every witness.

A replayed trace is a real execution, so every step of it the simulator agreed on must be an edge
of the certificate; a trace that takes an unlisted edge refutes the completeness claim without any
solver. The second engine's induction is bounded by `maxsteps` (10 by default); a smaller bound
can only turn an acceptance into a rejection. `attack.py` gives it the length the untouched
certificate needed plus two. Before the solver runs, the design's outputs stop being ports and
`opt_clean` removes every cell outside the fan-in of the monitor (axivfifo: 5555 cells down to
196), which cannot change what `ok` does. A verdict is only one of the three conclusions Yosys
prints (`Induction step proven: SUCCESS!`, `model found for base case: FAIL!`, `Reached maximum
number of time steps`); a run that ends any other way (out of memory, solver time limit, a tool
error) is `aborted`, which is no verdict: such a case counts as not run, never as rejected.

A trace is evidence only if it is an execution the assumptions allow, so the checker also
refuses a trace that leaves an input without a value, that pulls reset again after releasing it,
or whose power-up state contradicts an initial value written in the RTL (the testbench writes a
power-up value only over unknown bits and reports a conflict).

`attack.py` tries to get a false certificate accepted: tampered certificates against the RTL,
and the original certificate against mutated RTL (the mutant's own graph is proved first to
decide whether the certificate became false). A false certificate that passes is a survivor.
Tampering: a real edge removed; the same edge removed together with every trace through it, so
that only the induction can catch it; an absent edge added as witnessed; an edge retargeted; an
undetermined edge promoted; reset pulled again inside a trace; an input dropped from a trace.

## Trust base, stated

Completeness rests on Yosys's reading of the RTL (`read_verilog`, `proc`) and on two SAT solvers
agreeing. Witnesses rest on Icarus Verilog. slang, which L1 uses, is not involved, so x5 is also
an independent check of L1. Not covered: several clocks, latches, designs Yosys cannot read,
synthesis pragmas in comments, and whether the stated reset polarity is the designer's.

One known gap in the witnesses: Icarus Verilog computes with unknown values (`x`), and its rules
for them are not those of any hardware (an `if` on an unknown takes the else branch). While a
register that matters is still unknown, a simulated pair is trusted, not proven. A transition the
model forbids is still caught (it refutes the certificate), so the exposure is an edge inside the
closure that only an unknown-value artefact reaches. Closing it needs either a check that no
register was unknown on the way, or a replay of the trace in the Yosys model.

## Run

    python selftest.py WORK      # six small designs with known answers, 21 expectations, about two minutes
    python run.py REPO MANIFEST.json X4_DESIGNS OUT --proposals proposals.json --jobs 6 --budget 420
    python post.py OUT --jobs 3 --attack 6 --attack-heavy 2 --heavy-seconds 90
    python audit.py OUT          # exit 0 only if every verification of every certificate ran and passed
    python make_proof.py OUT GALLERY

## Audit

`audit.py` answers, per certificate and per verification, pass, FAIL or NOT RUN: prover version,
same design in both tools, certificate consistent (recomputed by the audit itself, including the
projection of a supporting edge set), witnesses replayed, completeness by the second engine,
state names, guard labels, drawing read back, attack. Every result file carries the hash of the
certificate it is about and the hashes of the source files that made it; a result that does not
match what is on disk now counts as NOT RUN, never as a pass. `make_proof.py` reads only the audit.

Tools: Yosys 0.33, z3 (pip `z3-solver`), Icarus Verilog 12, Graphviz.
