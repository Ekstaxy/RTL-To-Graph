"""e8_fsm_extra: enrich L1 FSMs with values, encoding, RTL names, source lines, reachability and
(opt-in) counter-driven FSMs. Writes runs/e8_fsm_extra/<name>/fsm_ext.json (format: x4 FORMATS.md).

    uv run --package rtl2d-l1 python layers/l1_extract/experiments/e8_fsm_extra/e8_extract.py \
        --files layers/l1_extract/examples/rtl/uart_tx.sv --top uart_tx \
        [--counters] [--out runs/e8_fsm_extra/uart_tx] [-I DIR] [-D DEF] [--no-replay]

Library use (x4 loads this file with importlib, never via sys.path):

    run = annotate_design(files, top=T, cfg=RunConfig(mode="heuristic",
                          targets=frozenset({"block", "fsm", "timing"})))
    fsm_ext = enrich(run, counters=False)

Everything recorded as a simplification (renamed state, approximated lines, divergence from L1)
goes to `extra.simplifications` [{what, reason, lines[]}], an addition to FORMATS.md that maps
1:1 onto FsmGraph.simplifications.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import inspect
import json
import re
import sys
import time
from pathlib import Path

from rtl2d_l1.frontend import fsm as l1fsm
from rtl2d_l1.frontend import fsm_semantic
from rtl2d_l1.frontend.fsm_semantic import Machine, _mask, analyze, candidate_registers

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def _sib(name: str):
    """Load a sibling module of this experiment under a unique name (no sys.path changes)."""
    key = f"e8_fsm_extra_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


lines = _sib("lines")
states = _sib("states")
candidates = _sib("candidates")


def detect_defaults() -> dict:
    """seed / time_budget / samples_per_state that annotate_design's detect() call uses."""
    p = inspect.signature(fsm_semantic.detect).parameters
    return {k: p[k].default for k in ("seed", "time_budget", "samples_per_state")}


# ------------------------------------------------------------------ semantic probe
def semantic_probe(design, G, syn_keys: set[str], *, seed: int, time_budget: float | None,
                   samples: int) -> tuple[dict, bool]:
    """Replays fsm_semantic.detect's analysis loop (same order, one shared Machine, same seed),
    so the per-register results equal the ones annotate_design used, and reports whether the
    time budget cut the loop (detect does not expose this)."""
    M = Machine(design, seed)
    order = sorted(syn_keys) + sorted(set(candidate_registers(G)) - syn_keys)
    t0, out, exhausted = time.time(), {}, False
    for k in order:
        if time_budget is not None and time.time() - t0 > time_budget and k not in syn_keys:
            exhausted = True
            break
        out[k] = analyze(design, G, k, machine=M, seed=seed, samples_per_state=samples)
    return out, exhausted


# ------------------------------------------------------------------------ naming
def _simp(what: str, reason: str, locs=()) -> dict:
    ls = [{"file": x["file"], "line": x["line"]} for x in locs if x and x.get("line")]
    return {"what": what, "reason": reason, "lines": ls}


def onehot_renames(values: dict, bitidx: dict) -> tuple[dict, list]:
    """Bit-index naming: `localparam IDLE = 0; ... state[IDLE]` names the state 1 << IDLE.
    All states renamed when every bit has a constant, else only S_<v> fallbacks."""
    vals = list(values.values())
    if not vals or any(v is None or v <= 0 or v & (v - 1) for v in vals):
        return {}, []
    ks = {n: v.bit_length() - 1 for n, v in values.items()}
    full = all(k in bitidx for k in ks.values())
    ren, simp = {}, []
    for n, k in ks.items():
        b = bitidx.get(k)
        if b and b["name"] != n and (full or states.UNNAMED.match(n)):
            ren[n] = b["name"]
            simp.append(_simp(
                f"state '{n}' (value {values[n]}) named '{b['name']}'",
                f"one-hot bit index: {b['name']} = {k} is used as <state>[{b['name']}]"
                + ("" if full else "; only the S_<v> fallback was replaced"), [b]))
    return ren, simp


def table_renames(values: dict, table: dict, cand, reason: str) -> tuple[dict, list]:
    """Rename states selected by `cand(name, value)` from a value -> {name, file?, line?}
    table."""
    ren, simp = {}, []
    for n, v in values.items():
        if v is None or not cand(n, v) or v not in table:
            continue
        new = table[v]["name"]
        if new != n:
            ren[n] = new
            simp.append(_simp(f"state '{n}' (value {v}) named '{new}'", reason.format(**table[v]),
                              [table[v]] if table[v].get("line") else []))
    return ren, simp


def apply_renames(d: dict, ren: dict, simp: list) -> dict:
    """Rename states in an FSM dict in place; renames that would collide are dropped (logged)."""
    names = [s["name"] for s in d["states"]]
    final = [ren.get(n, n) for n in names]
    dup = {x for x in final if final.count(x) > 1}
    for n in list(ren):
        if ren[n] in dup:
            simp.append(_simp(f"state '{n}' kept its name", f"'{ren[n]}' would collide"))
            del ren[n]
    if not ren:
        return {}
    for s in d["states"]:
        s["name"] = ren.get(s["name"], s["name"])
    if d.get("reset_state"):
        d["reset_state"] = ren.get(d["reset_state"], d["reset_state"])
    for t in d["transitions"]:
        t["src"] = ren.get(t["src"], t["src"]) if t["src"] != "*" else "*"
        t["dst"] = ren.get(t["dst"], t["dst"])
    return ren


# ------------------------------------------------------------------- source lines
def _loc(r) -> dict:
    return {"file": r.file, "line": r.line}


def _uniq_lines(locs) -> list[dict]:
    seen = {(x["file"], x["line"]) for x in locs if x.get("line")}
    return [{"file": f, "line": ln} for f, ln in sorted(seen)]


def _expand_default(recs, names: list[str]) -> list:
    """fsm._expand_default on line records (default: -> every state not listed)."""
    out = []
    for r in recs:
        if r.src.startswith("__default__"):
            covered = set(filter(None, r.src.split(":", 1)[1].split(",")))
            out += [_with_src(r, s) for s in names if s not in covered]
        else:
            out.append(r)
    return out


def _with_src(r, s):
    c = copy.copy(r)
    c.src = s
    return c


def lines_exact(d: dict, walk, pre_names: list[str], ren: dict, simp: list, ev=None) -> dict:
    """transition_lines for a syntactic FSM: the walker is L1's own visitor, so records carry
    L1's (src, dst, cond); `*` sources are listed under `*->D` and under each concrete `S->D`
    for which the record can fire in S (`ev(rec, name)`: state-decided guards hold and no later
    statement surely overwrites it; unknown -> listed)."""
    recs = _expand_default([r for r in walk.recs if not r.in_reset], pre_names)
    got = {(r.src, r.dst, r.cond) for r in recs}
    want = {(t["src"], t["dst"], t["cond"]) for t in d["_pre_transitions"]}
    if got != want:
        simp.append(_simp("transition_lines may be incomplete",
                          f"e8 line walker diverged from L1 (missing {sorted(want - got)[:3]}, "
                          f"extra {sorted(got - want)[:3]})"))
    tl: dict[str, list] = {}
    final = [ren.get(n, n) for n in pre_names]
    pruned = 0
    for r in recs:
        dst = ren.get(r.dst, r.dst)
        srcs = [ren.get(r.src, r.src)]
        if r.src == "*":
            ok = [x for x in final if ev is None or ev(r, x)]
            pruned += len(final) - len(ok)
            srcs = ["*", *ok]
        for s in srcs:
            tl.setdefault(f"{s}->{dst}", []).append(_loc(r))
    if pruned:
        simp.append(_simp(f"{pruned} (state, `*` assignment) line pair(s) not listed per state",
                          "the assignment cannot fire in that state (enclosing state test "
                          "false, or surely overwritten later in its block); still listed "
                          "under '*->DST'"))
    return {k: _uniq_lines(v) for k, v in sorted(tl.items())}


def star_eval(values: dict, walk, read_keys, cmap, width, M, G, known):
    """ev(rec, state name) for lines_exact: can the record fire in that state?"""
    memo: dict = {}

    def ev(r, name):
        v = values.get(name)
        if v is None:
            return True
        ok, _ = lines.guards_hold(r, v, M, read_keys, G, memo, known, walk.wires)
        ctx = lines.make_ctx(v, M, read_keys, G, memo, known, walk.wires)
        return ok and not lines.overwritten(r, v, ctx, read_keys, width)

    return ev


def lines_by_value(d, values, walk, read_keys, cmap, width, M, simp, reg, G,
                   known=None) -> dict:
    """transition_lines for semantic / counter FSMs: records that can produce value s -> d
    (destination value, source test or default, state-only guards evaluated at s)."""
    tl: dict[str, list] = {}
    live = [w for w in walk.writes if not w["in_reset"]]
    fallback = _uniq_lines(live)
    bitwise = any(w.get("bitwise") for w in live)  # `oh[K] <= ...`: holds are driven too
    used_fallback = []
    for t in d["transitions"]:
        s, dv = values.get(t["src"]), values.get(t["dst"])
        if s is None or dv is None:
            continue
        hits = lines.applicable(walk.recs, s, dv, width, walk.states, cmap, M, read_keys,
                                G, known, walk.wires)
        locs = _uniq_lines(_loc(r) for r, _ in hits)
        if not locs and (s != dv or bitwise) and fallback:
            locs = fallback
            used_fallback.append(f"{t['src']}->{t['dst']}")
        tl[f"{t['src']}->{t['dst']}"] = locs
    if used_fallback:
        simp.append(_simp(
            f"transition_lines of {len(used_fallback)} edge(s) approximated "
            f"({', '.join(used_fallback[:4])}{', ...' if len(used_fallback) > 4 else ''})",
            f"no whole-value constant assignment to {reg} produces them (bit-wise or computed "
            "next state); every non-reset assignment to the register is listed", fallback))
    return tl


def reset_ports(G) -> list[str]:
    """Names of the signals that drive a RESET edge in the graph."""
    keys = {a for a, _, e in G.g.edges(data=True) if e["type"] == lines.EdgeType.RESET}
    return sorted({G.nodes[k].name for k in keys if k in G.nodes})


def reset_line(walk, pre_reset: str | None, reset_value: int | None, width: int, cmap: dict,
               reset_name: str | None = None, reset_names=(), simp=None) -> dict | None:
    """Line of the reset assignment: the last in-reset record of the reset state (by name, then
    by value); else a record writing the reset value under a condition naming the reset signal
    (`s <= rst ? IDLE : nxt`); with no reset value known, the first constant assignment whose
    enclosing condition is true when a RESET-edge signal is named (`if (!resetn || soft)`),
    logged in `simp`."""
    m = _mask(width)

    def val(r):
        v = r.dst_value if r.dst_value is not None else lines.resolve(r.dst or "", walk.states,
                                                                       cmap)
        return None if v is None else v & m

    rs = [r for r in walk.recs if r.in_reset]
    hit = [r for r in rs if pre_reset is not None and r.dst == pre_reset]
    if not hit and reset_value is not None:
        hit = [r for r in rs if val(r) == reset_value]
    if not hit and reset_value is not None and reset_name:
        pat = re.compile(rf"(?<![\w.]){re.escape(reset_name)}(?![\w])")
        hit = [r for r in walk.recs if not r.in_reset and r.rel is None
               and val(r) == reset_value and pat.search(r.cond)]
    if not hit and reset_value is None and pre_reset is None:
        return _reset_by_port(walk, reset_names, simp)
    return _loc(hit[-1]) if hit else None


def _reset_by_port(walk, names, simp) -> dict | None:
    if not names:
        return None
    pat = re.compile(r"(?<![\w.])(" + "|".join(map(re.escape, names)) + r")(?![\w])")
    for r in sorted(walk.recs, key=lambda r: (r.file, r.line)):
        if r.in_reset or r.rel is not None or not r.guards:
            continue
        expr, pol, text = r.guards[0]
        if pol and pat.search(text) and (r.dst_value is not None or r.dst):
            if simp is not None:
                simp.append(_simp(
                    f"reset_line = line {r.line} (assignment of {r.dst})",
                    "no reset state known (L1 / semantic engine); first constant assignment "
                    f"under a condition naming a reset signal ({text})", [_loc(r)]))
            return _loc(r)
    return None


# ------------------------------------------------------------------------- extra
def build_extra(design, G, d: dict, *, sem_r, prov: dict, engine: str, walk=None,
                read_keys=None, rename: bool = True, seed: int = 0) -> dict:
    """Mutates `d` (renames) and returns the `extra` object for one FSM dict."""
    key = f"{d['instance']}.{d['state']}"
    simp: list[dict] = []
    if key not in G.nodes:
        return {"graph_key": None, "file": None, "decl_line": None, "width": None,
                "values": {s["name"]: None for s in d["states"]}, "encoding": "other",
                "unnamed": [], "reached": None, "transition_lines": {}, "reset_line": None,
                "outputs_semantic": None, "engine": engine, "provenance": prov,
                "simplifications": [_simp("no extra data", f"{key} is not a graph node")]}
    n = G.nodes[key]
    width = n.width or 1
    semantic = d["style"] == "semantic"
    if walk is None:
        if semantic:
            walk, read_keys = lines.walk_ext(design, G, key)
        else:
            walk, read_keys = lines.walk_exact(design, G, key, n.enum_values), {key}
    chain = lines.next_chain(G, key) if semantic else set()
    insts = sorted({G.nodes[k].inst for k in set(read_keys) | chain})
    cmap = states.const_map(design, G, key, insts)
    pre_names = [s["name"] for s in d["states"]]
    pre_reset = d.get("reset_state")
    d["_pre_transitions"] = copy.deepcopy(d["transitions"])
    pre_vals = states.state_values(d["states"], cmap, width)
    ren: dict = {}
    if rename:
        ren = _names(design, G, key, d, pre_vals, read_keys, insts, semantic, simp)
    values = states.state_values(d["states"], cmap, width)
    for old, new in ren.items():  # renamed constants may shadow cmap: keep the pre value
        values[new] = pre_vals[old]
    M = Machine(design, seed + 1)
    if semantic:
        tl = lines_by_value(d, values, walk, read_keys, cmap, width, M, simp, n.name, G,
                            lines.inactive_reset(sem_r))
    else:
        tl = lines_exact(d, walk, pre_names, ren, simp,
                         star_eval(values, walk, read_keys, cmap, width, M, G,
                                   lines.inactive_reset(sem_r)))
    del d["_pre_transitions"]
    reset_v = values.get(d.get("reset_state")) if d.get("reset_state") else None
    rname = None
    if sem_r is not None and not sem_r.error:
        reset_v = sem_r.reset_value if reset_v is None else reset_v
        if sem_r.reset_signal in G.nodes:
            rname = G.nodes[sem_r.reset_signal].name
    out_sem = None
    if semantic:
        out_sem = states.outputs_rule(G, key, set(read_keys), {key} | chain)
        if len(read_keys) > 1:
            simp.append(_simp("outputs_semantic follows port aliases",
                              "fsm.py output rule applied to the register and its aliases "
                              + ", ".join(sorted(set(read_keys) - {key}))))
    return {
        "graph_key": key,
        "file": n.file,
        "decl_line": n.line,
        "width": width,
        "values": values,
        "encoding": states.encoding(values, d["transitions"], states.is_enum(design, G, key)),
        "unnamed": states.unnamed_states(values, cmap),
        "reached": _reached(sem_r, values, simp),
        "transition_lines": tl,
        "reset_line": reset_line(walk, pre_reset, reset_v, width, cmap, rname,
                                 reset_ports(G), simp),
        "outputs_semantic": out_sem,
        "engine": engine,
        "provenance": prov,
        "simplifications": simp,
    }


def _names(design, G, key, d, pre_vals, read_keys, insts, semantic, simp) -> dict:
    ren: dict = {}
    if semantic:
        bitidx = lines.bit_index_constants(design, G, set(read_keys))
        r1, s1 = onehot_renames(pre_vals, bitidx)
        ren.update(r1)
        simp += s1
        if all(v and v & (v - 1) == 0 for v in pre_vals.values()):
            wires = lines.bit_alias_wires(design, G, set(read_keys))
            rw, sw = table_renames(
                pre_vals, wires, lambda nm, v: nm not in ren and states.UNNAMED.match(nm),
                "one-hot bit tap `assign {name} = <state>[K]`")
            ren.update(rw)
            simp += sw
        table = states.alias_value_names(design, G, key, insts)
        r2, s2 = table_renames(
            pre_vals, table, lambda nm, v: nm not in ren and states.UNNAMED.match(nm),
            "constant of instance {inst} holding the next-state logic / a port alias")
        ren.update(r2)
        simp += s2
    macros = lines.macro_names(design, G, key, set(read_keys))
    r3, s3 = table_renames(
        pre_vals, macros,
        lambda nm, v: nm not in ren and (states.UNNAMED.match(nm) or l1fsm._lit_value(nm)),
        "state code written as the macro `{name}")
    ren.update(r3)
    simp += s3
    return apply_renames(d, ren, simp)


def _reached(r, values: dict, simp: list) -> list[str] | None:
    if r is None or r.error:
        return None
    if any(v is None for v in values.values()):
        simp.append(_simp("reached = null", "a state value is unknown, cannot map execution"))
        return None
    got = set(r.states)
    return [nm for nm, v in values.items() if v in got]


# ------------------------------------------------------------------------- enrich
def enrich(run, *, counters: bool = False, seed: int | None = None,
           time_budget: float | None = None, report: list | None = None,
           replay: bool = True) -> list[dict]:
    """One dict per FSM of `run.fsms` (FSM.to_json() + "extra"), then (counters=True) one per
    admitted counter-driven FSM. `seed`/`time_budget` default to what annotate_design used.
    `report`, when given, receives one decision row per counter candidate. replay=False skips
    the detect replay (cost ~ the semantic budget on large designs): `reached` then comes from
    one analyze() per FSM and `budget_exhausted` is null."""
    design, G = run.design, run.graph
    dflt = detect_defaults()
    seed = dflt["seed"] if seed is None else seed
    budget = dflt["time_budget"] if time_budget is None else time_budget
    syn_keys = {f"{f.instance}.{f.state}" for f in run.fsms if f.style != "semantic"}
    syn_keys &= set(G.nodes)
    sem, exhausted = {}, None
    if replay:
        sem, exhausted = semantic_probe(design, G, syn_keys, seed=seed, time_budget=budget,
                                        samples=dflt["samples_per_state"])
    prov = {"seed": seed, "time_budget": budget, "budget_exhausted": exhausted}
    out = []
    for f in run.fsms:
        d = copy.deepcopy(f.to_json())
        key = f"{f.instance}.{f.state}"
        r = sem.get(key)
        late = r is None and key in G.nodes
        if late:
            r = analyze(design, G, key, seed=seed, samples_per_state=dflt["samples_per_state"])
        d["extra"] = build_extra(design, G, d, sem_r=r, prov=prov, engine="l1-hybrid", seed=seed)
        if late and replay:
            d["extra"]["simplifications"].append(_simp(
                "reached from a separate analyze() run",
                "the replayed detect loop did not reach this register within the budget"))
        out.append(d)
    if counters:
        skip = {f"{f.instance}.{f.state}" for f in run.fsms}
        rows = candidates.evaluate(design, G, skip, seed=seed)
        cprov = {"seed": seed, "time_budget": None, "budget_exhausted": False}
        for row in rows:
            if row["admitted"]:
                d, walk, rk, how = candidates.build(design, G, row, seed=seed)
                d["extra"] = build_extra(design, G, d, sem_r=row["r"], prov=cprov,
                                         engine="e8-counter", walk=walk, read_keys=rk,
                                         rename=False, seed=seed)
                d["extra"]["simplifications"] += _guard_simps(how)
                out.append(d)
            if report is not None:
                report.append({k: v for k, v in row.items() if k not in ("r", "clear_keys")})
    return out


def _guard_simps(how: dict) -> list[dict]:
    out = []
    if how["derived"]:
        out.append(_simp(
            f"hold guard derived for {len(how['derived'])} self-loop(s) "
            f"({', '.join(how['derived'][:4])}{', ...' if len(how['derived']) > 4 else ''})",
            "no assignment creates a hold; guard = !(OR of the recovered guards of every "
            "assignment that can fire in that state)"))
    if how["datapath"]:
        out.append(_simp(
            f"{len(how['datapath'])} edge(s) labelled '{candidates.DATAPATH}' "
            f"({', '.join(how['datapath'][:4])}{', ...' if len(how['datapath']) > 4 else ''})",
            "no syntactic condition recovered (sampled QM cubes are not used as labels)"))
    return out


# ---------------------------------------------------------------------------- CLI
def _summary(fx: list[dict]) -> list[str]:
    rows = []
    for d in fx:
        e = d["extra"]
        names = ", ".join(s["name"] for s in d["states"])
        tl = e["transition_lines"]
        lined = sum(1 for t in d["transitions"] if tl.get(f"{t['src']}->{t['dst']}"))
        rows.append(
            f"{e['graph_key']:<34} {e['engine']:<10} {str(d.get('semantic_check')):<17} "
            f"{e['encoding']:<7} states={len(d['states'])} unnamed={len(e['unnamed'])} "
            f"lines={lined}/{len(d['transitions'])} "
            f"reset_line={(e['reset_line'] or {}).get('line')} [{names}]")
    return rows


def main(argv: list[str]) -> int:
    from rtl2d_l1.pipeline import RunConfig, annotate_design

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", nargs="+", required=True)
    ap.add_argument("--top", required=True)
    ap.add_argument("--counters", action="store_true", help="also admit counter-driven FSMs")
    ap.add_argument("--out", default=None, help="output dir (default runs/e8_fsm_extra/<top>)")
    ap.add_argument("-I", "--include-dir", action="append", default=[])
    ap.add_argument("-D", "--define", action="append", default=[])
    ap.add_argument("--time-budget", type=float, default=None,
                    help="budget of the replayed detect loop (default: L1's)")
    ap.add_argument("--no-replay", action="store_true",
                    help="skip the detect replay (budget_exhausted = null)")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else ROOT / "runs" / "e8_fsm_extra" / a.top
    t0 = time.time()
    run = annotate_design(a.files, top=a.top, include_dirs=a.include_dir, defines=a.define,
                          cfg=RunConfig(mode="heuristic",
                                        targets=frozenset({"block", "fsm", "timing"})))
    t1 = time.time()
    report: list = []
    fx = enrich(run, counters=a.counters, time_budget=a.time_budget, report=report,
                replay=not a.no_replay)
    t2 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    (out / "fsm_ext.json").write_text(json.dumps(fx, indent=1), encoding="utf-8")
    if a.counters:
        (out / "counter_candidates.json").write_text(json.dumps(report, indent=1),
                                                     encoding="utf-8")
    print(f"L1 {t1 - t0:.1f}s, e8 {t2 - t1:.1f}s -> {out / 'fsm_ext.json'} ({len(fx)} FSMs)")
    for line in _summary(fx):
        print(" ", line)
    for row in report:
        tag = "ADMIT " if row["admitted"] else "reject"
        print(f"  counter {tag} {row['key']:<30} w={row['width']} {row['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
