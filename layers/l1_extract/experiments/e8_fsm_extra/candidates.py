"""e8 candidates: counter-driven FSMs (plan §2 Stage 1, M4, opt-in `--counters`).

Library module (no CLI of its own); driven by

    uv run --package rtl2d-l1 python layers/l1_extract/experiments/e8_fsm_extra/e8_extract.py \
        --files layers/l1_extract/data/rtl/picorv32/picosoc/simpleuart.v --top simpleuart --counters

`fsm_semantic.candidate_registers` skips every register that is an arithmetic source of itself
(`x <= x + k`). This module re-admits such a register as an FSM only when all of these hold
(replicated locally; L1 src is not changed):

  R1 width <= 8
  R2 `analyze()` from reset succeeds and reaches 3..48 values        (3 = detect's `shaped` rule)
  R3 not `_loads_data` (no (nearly) as-wide register / input copied into it)
  R4 average out-degree (distinct edges incl. self-loops / states) <= 3.5   (as detect)
  R6 every non-reset write is a constant or a `+-k` update (no shift-in / data load / bit
     write; checked before R5, it is what lets every edge carry an RTL guard)
  R5 the input-chosen successor differs between at least two states: per state, the set of
     (relative successor, guard) over its non-self edges, where the relative successor is
     dst-src mod 2**w (the wrap of a contiguous value range, hi->lo / lo->hi, counts as +1 / -1)
     and the guard is the syntactic condition recovered for that edge (lines.applicable, with
     guards that only test the counter's own value evaluated and dropped), '?' when none.
     Edges into a "global target" (a constant reached from every other state: clear / flush /
     abort loads), edges produced only by a constant assignment that can fire in every state
     (a global load the semantic run may never take, e.g. `flush_i` tied to 1'b0 by the parent)
     and states without remaining non-self edges (saturation) are ignored.
     When every state has the same set of relative successors, the wrap states (hi -> lo /
     lo -> hi edge) are left out of the comparison: their extra terminal-count guard
     (`cnt == 3`) is the counter's own wrap, not an input-chosen successor.
     A state whose set is a strict subset of another state's set (the boundary of a saturating
     up/down counter: 0 cannot count down) is not a different successor. R5 holds when at
     least two different maximal sets remain; a pure counter (one relative successor under one
     guard everywhere) fails R5.

R5 is stricter than the literal "relative successor not the same everywhere" in two ways (wrap
normalisation, global targets ignored) because the literal rule admits every mod-N counter
(`q == 9 ? 0 : q + 1`) and the sync_fifo pointers (flush edges); it is looser in one: equal
relative successors under different recovered guards (simpleuart `recv_state`: `!ser_rx` in
state 0, divider compares elsewhere) also count as a differing input-chosen successor. Guards come
from the RTL text, not from sampled QM cubes, because sampled datapath conditions are noisy.

Edge labels (`build`): the recovered syntactic condition of the edge; for a hold self-loop
without its own assignment, !(exit_1 || exit_2 ...) when every assignment that can fire in that
state was recovered (derived, logged as a simplification); otherwise '<datapath condition>'.
Sampled QM cubes are never used as labels (they contradict the RTL on datapath-driven holds).
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

from rtl2d_l1.frontend.fsm_semantic import Machine, _loads_data, _mask, analyze

HERE = Path(__file__).resolve().parent
DATAPATH = "<datapath condition>"


def _sib(name: str):
    key = f"e8_fsm_extra_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


lines = _sib("lines")


def counter_keys(G, skip: set[str]) -> list[str]:
    """Registers candidate_registers drops only because they are arith sources of themselves."""
    out = []
    for k, n in sorted(G.nodes.items()):
        if k in skip or not n.is_state or n.depth is not None or not 1 <= n.width <= 16:
            continue
        if k in n.arith_srcs:
            out.append(k)
    return out


def _rel(s: int, d: int, width: int, lo: int, hi: int, contiguous: bool) -> int:
    m = _mask(width)
    if contiguous and s == hi and d == lo:
        return 1
    if contiguous and s == lo and d == hi:
        return -1 & m
    return (d - s) & m


def global_targets(r) -> set[int]:
    """Constant destinations reached from every other reached state (clear / abort / flush
    loads); their edges say nothing about the counting structure."""
    out = set()
    for d in r.states:
        if all((s, d) in r.edges for s in r.states if s != d):
            out.add(d)
    return out


def signatures(G, r, width: int, walk, read_keys, M) -> dict[int, frozenset]:
    """Per state: {(relative successor, recovered guard text or '?')}, one entry per assignment
    producing a non-self edge. Ignored: edges into a global target (reached from every other
    state) and constant assignments that can fire in every state ("global loads": clear /
    flush, also when the semantic run never takes them, e.g. `flush_i` tied to 0)."""
    vals = sorted(r.states)
    lo, hi = vals[0], vals[-1]
    contiguous = vals == list(range(lo, hi + 1))
    skip = global_targets(r) if len(vals) >= 3 else set()
    fires = {s: lines.firing(walk.recs, s, width, walk.states, {}, M, read_keys, G,
                             lines.inactive_reset(r), walk.wires) for s in vals}
    loads = set.intersection(*({id(x) for x, _, _ in fires[s] if x.rel is None}
                               for s in vals)) if vals else set()
    sig: dict[int, set] = {s: set() for s in vals}
    for s, d in sorted(set(r.edges)):
        if s == d or d in skip:
            continue
        hits = [(x, t) for x, v, t in fires[s] if v == d]
        own = [t for x, t in hits if id(x) not in loads]
        if hits and not own:
            continue  # only a global load produces this edge
        rel = _rel(s, d, width, lo, hi, contiguous)
        sig[s] |= {(rel, t) for t in own} or {(rel, "?")}
    return {s: frozenset(x) for s, x in sig.items()}


def wrap_states(r) -> set[int]:
    """States with a wrap edge of a contiguous value range (hi -> lo or lo -> hi)."""
    vals = sorted(r.states)
    if not vals or vals != list(range(vals[0], vals[-1] + 1)):
        return set()
    lo, hi = vals[0], vals[-1]
    return {s for s, d in set(r.edges) if (s, d) in ((hi, lo), (lo, hi))}


def literal_rule(r, width: int) -> bool:
    """The plan's rule as written: the per-state sets of relative successors (dst - src mod
    2**w over non-self edges) are not the same for every state (no wrap normalisation, no
    global targets, no guards). Reported next to R5 for the sweep."""
    m = _mask(width)
    per: dict[int, set] = {s: set() for s in r.states}
    for s, d in set(r.edges):
        if s != d:
            per[s].add((d - s) & m)
    return len({frozenset(x) for x in per.values() if x}) >= 2


def decide(design, G, key: str, M, Mc, seed: int) -> dict:
    """One decision row: {key, width, admitted, reason, ...}; admitted rows also carry the
    SemanticFSM `r`."""
    n = G.nodes[key]
    row: dict = {"key": key, "width": n.width, "admitted": False, "line": n.line}
    if n.width > 8:
        return {**row, "reason": f"R1 width {n.width} > 8"}
    if _loads_data(G, key):  # structural, checked before the (costly) execution
        return {**row, "reason": "R3 loaded from (nearly) as-wide data"}
    t0 = time.time()
    r = analyze(design, G, key, machine=M, seed=seed)
    row["n_states"] = len(r.states)
    row["analyze_s"] = round(time.time() - t0, 2)
    if r.error:
        return {**row, "reason": f"R2 {r.error}"}
    if len(r.states) < 3:
        return {**row, "reason": f"R2 only {len(r.states)} reachable values"}
    avg = len(set(r.edges)) / max(1, len(r.states))
    row["avg_out"] = round(avg, 2)
    if avg > 3.5:
        return {**row, "reason": f"R4 average out-degree {avg:.2f} > 3.5"}
    row["literal"] = literal_rule(r, n.width)
    walk, read_keys = lines.walk_ext(design, G, key, relative=True)
    odd = data_writes(walk)
    if odd:
        return {**row, "reason": "R6 written with a data-dependent value (not a constant / "
                                 f"+-k update) at line(s) {odd[:3]}"}
    sig = signatures(G, r, n.width, walk, read_keys, Mc)
    row["global_targets"] = sorted(global_targets(r))
    rels = {frozenset(rel for rel, _ in x) for x in sig.values() if x}
    if len(rels) == 1:  # same moves everywhere: only guards can differ; the wrap state's extra
        wrap = wrap_states(r)  # terminal-count compare (`cnt == N`) is not a different guard
        row["wrap_states"] = sorted(wrap)
        sig = {st: x for st, x in sig.items() if st not in wrap}
    distinct = {x for x in sig.values() if x}
    maximal = {x for x in distinct if not any(x < y for y in distinct)}
    row["signatures"] = len(maximal)
    if len(maximal) < 2:
        only = sorted(next(iter(maximal))) if maximal else []
        sat = " (boundary states only drop moves: saturating counter)" if distinct != maximal \
            else ""
        return {**row, "reason": "R5 pure counter: one (relative successor, guard) everywhere "
                                 f"{only[:2]}{sat}"}
    return {**row, "admitted": True, "reason": "R1-R6 hold", "r": r}


def evaluate(design, G, skip: set[str], *, seed: int = 0) -> list[dict]:
    M = Machine(design, seed)
    Mc = Machine(design, seed + 1)
    return [decide(design, G, k, M, Mc, seed) for k in counter_keys(G, skip)]


def data_writes(walk) -> list[int]:
    """Lines of non-reset writes to the register (or its next-state wires) that are neither a
    recorded constant nor a +-k update (shift-ins, loads from other signals, bit writes)."""
    recorded = {r.wline for r in walk.recs if not r.in_reset}
    return sorted({w["line"] for w in walk.writes if not w["in_reset"]
                   and (w["bitwise"] or (w["file"], w["line"]) not in recorded)})


def complete(walk) -> bool:
    """Every exit of a state is a recorded assignment (so a hold guard can be derived)."""
    return not data_writes(walk)


def edge_guard(fires, s: int, d: int, full: bool) -> tuple[str, str]:
    """(guard, source) for edge s -> d: 'syntactic' (recorded assignments producing it),
    'derived' (hold = negated exits), 'datapath' (nothing recoverable)."""
    texts = list(dict.fromkeys(t for _, v, t in fires if v == d))
    if texts:
        return (texts[0] if len(texts) == 1 else " || ".join(f"({t})" for t in texts),
                "syntactic")
    if s == d and full:
        g = lines.hold_guard(fires, s)
        if g is not None:
            return g, "derived"
    return DATAPATH, "datapath"


def build(design, G, row: dict, *, seed: int = 0) -> tuple[dict, object, set[str], dict]:
    """L1-shaped FSM dict (FSM.to_json() keys) for an admitted counter, plus the extended walk
    used for guards and lines, the read keys and {source: [edge names]} of the guards."""
    key, r = row["key"], row["r"]
    n = G.nodes[key]
    width = n.width
    Mc = Machine(design, seed + 1)
    walk, read_keys = lines.walk_ext(design, G, key, relative=True)
    full = complete(walk)
    name = {v: f"S_{v}" for v in r.states}
    trans: list = []
    src: dict[str, list] = {"syntactic": [], "derived": [], "datapath": []}
    fires = {s: lines.firing(walk.recs, s, width, walk.states, {}, Mc, read_keys, G,
                             lines.inactive_reset(r), walk.wires) for s in r.states}
    for s, d in sorted(set(r.edges)):
        guard, how = edge_guard(fires[s], s, d, full)
        src[how].append(f"{name[s]}->{name[d]}")
        trans.append({"src": name[s], "dst": name[d], "cond": guard})
    d = {
        "module": n.module,
        "instance": n.inst,
        "state": n.rel,
        "next": None,
        "style": "semantic",
        "states": [{"name": name[v], "value": str(v)} for v in r.states],
        "reset_state": name.get(r.reset_value),
        "transitions": trans,
        "outputs": [],
        "warnings": [
            "e8: counter-driven FSM admitted by the relaxed candidate rule "
            f"(R1-R6; {row['signatures']} distinct successor signatures"
            + (f"; edges into global targets {row['global_targets']} ignored for R5"
               if row["global_targets"] else "")
            + ")",
            f"e8: guards {len(src['syntactic'])} syntactic, {len(src['derived'])} derived "
            f"hold, {len(src['datapath'])} datapath",
        ],
        "semantic_check": "semantic-only",
    }
    return d, walk, read_keys, src
