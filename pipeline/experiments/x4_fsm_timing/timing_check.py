"""x4 timing gates T1-T3 on a TimingDiagram (T4 determinism: orchestrator; T5: L3 wave_check).

    uv run python pipeline/experiments/x4_fsm_timing/timing_check.py DIAGRAM.json GRAPH.json \
        SIM.json [WAVE.vcd] [--fsm-ext FSM_EXT.json]

(sim.json's "vcd" is used when WAVE.vcd is omitted; a relative path is tried from the current
directory, then from the repo root.)

Re-derives everything from the VCD and graph.json without calling timing_bridge, so a bridge bug
cannot hide itself:
- T1 replay: every drawn sample has t == its domain's posedge #cycle in the VCD and v equals the
  VCD value sampled there (vcd.Vcd.at: last change strictly before the edge).
- T2 arrows: path[0]/path[-1] are the graph nodes of the end lanes, every hop is a
  DATA/CONTROL/ADDR/PORT edge, the is_state count after the source equals `regs`, kind agrees
  with regs/cycles/domains (cdc: forward in time, through a register pair: domain-A registers
  then domain-B ones, ends included), both ends change in the VCD at their cycles, every via
  line is on the path's edges; `witnessed` counts arrows whose VCD-visible intermediate nodes
  change too.
  With fsm_ext (optional), a same-domain next-cycle path through an FSM state register whose
  taken transition (state at src cycle -> state at dst cycle) has a known guard must contain,
  before that register, a node the guard reads (else the arrow fails). `evidence` splits arrows
  into comb (same-cycle), fsm_guard (register = FSM, guard reads the path), structural (register
  path + witness only: write conditions not evaluated) and cdc.
- T3 accounting, per domain: drawn cycles + gap cycles == posedges in [first window t0, last
  window t1]; drawn cycles are exactly the posedges outside every gap; every gap lies inside a
  window and hides no lane change.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PATH_TYPES = {"DATA", "CONTROL", "ADDR", "PORT"}
_VIA_LINE = re.compile(r"@L(\d+)")
_IDENT = re.compile(r"(?<![\w$'])[A-Za-z_][\w$]*")
MAX_LANES, MAX_CYCLES = 12, 30


def _sibling(name: str):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


x4_tools = _sibling("x4_tools")
ts = x4_tools.x4("timing_spec")
vcdmod = x4_tools.x4("vcd")


class _Env:
    def __init__(self, d, vcd, graph: dict, sim: dict, fsm_ext: list[dict] | None):
        self.d, self.vcd, self.graph, self.sim = d, vcd, graph, sim
        self.dut = sim.get("dut_path") or "tb.dut"
        self.inst = next((p for p in graph["tops"] if graph["instances"][p]["module"] == d.module),
                         graph["tops"][0])
        self.edges = {dm.id: vcd.posedges(f"{self.dut}.{dm.clock}") for dm in d.domains}
        self.lanes = {ln.id: (ln, dm.id) for dm in d.domains for ln in dm.lanes}
        self.fsms = _fsms(fsm_ext, graph, self.inst) if fsm_ext is not None else None

    def name(self, signal: str) -> str:
        return f"{self.dut}.{signal}"

    def changed(self, name: str, dom: str, c: int) -> bool:
        e = self.edges[dom]
        if c <= 0 or c >= len(e):
            return False
        return self.vcd.at(name, e[c]) != self.vcd.at(name, e[c - 1])

    def hier(self, key: str) -> str | None:
        return self.dut + key[len(self.inst):] if key.startswith(self.inst + ".") else None


def _fsms(fsm_ext: list[dict], graph: dict, inst: str) -> dict[str, tuple[dict, list]]:
    """graph key -> (sampled value -> state name, [(src, dst, guard)]) for top-instance FSMs."""
    out = {}
    for f in fsm_ext:
        ex = f.get("extra") or {}
        key = ex.get("graph_key") or f"{f.get('instance')}.{f.get('state')}"
        node = graph["nodes"].get(key)
        if node is None or node.get("inst") != inst:
            continue
        width = int(ex.get("width") or node.get("width") or 1)
        enum = {}
        for name, v in (ex.get("values") or {}).items():
            if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
                enum[format(int(v), "x") if width > 1 else str(int(v))] = name
        out[key] = (enum, [(str(t.get("src")), str(t.get("dst")), str(t.get("cond") or ""))
                           for t in f.get("transitions") or []])
    return out


def check(d, vcd, graph: dict, sim: dict, fsm_ext: list[dict] | None = None) -> dict:
    """-> {"replay": {...}, "arrows": {...}, "accounting": {...}} (T1, T2, T3), each with "ok".
    fsm_ext (optional) enables the FSM-guard test of T2."""
    env = _Env(d, vcd, graph, sim, fsm_ext)
    return {"replay": _replay(env), "arrows": _arrows(env), "accounting": _accounting(env)}


# ---- T1 -----------------------------------------------------------------------------------
def _replay(env: _Env) -> dict:
    n, bad, missing = 0, [], []
    for ln, dom in env.lanes.values():
        name = env.name(ln.signal)
        if not env.vcd.has(name):
            missing.append(ln.signal)
            continue
        e = env.edges[dom]
        for s in ln.values:
            n += 1
            want_t = e[s.cycle] if 0 <= s.cycle < len(e) else None
            got = env.vcd.at(name, s.t)
            if want_t != s.t or got != s.v:
                bad.append({"lane": ln.id, "cycle": s.cycle, "t": s.t, "drawn": s.v,
                            "vcd": got, "posedge_t": want_t})
    return {"ok": not bad and not missing and n > 0, "samples": n, "mismatches": len(bad),
            "first": bad[:10], "missing_signals": missing}


# ---- T2 -----------------------------------------------------------------------------------
def _arrows(env: _Env) -> dict:
    g = env.graph
    hop: dict[tuple[str, str], list[str]] = {}
    for e in g["edges"]:
        if e["type"] in PATH_TYPES:
            hop.setdefault((e["src"], e["dst"]), []).append(e["via"])
    fails, witnessed = [], 0
    evidence = {"comb": 0, "fsm_guard": 0, "structural": 0, "cdc": 0}
    for a in env.d.arrows:
        why, wit = _arrow(env, a, hop)
        if why is None:
            why, ev = _fsm_guard(env, a)
            if why is None:
                evidence[ev] += 1
        if why:
            fails.append({"arrow": a.id, "why": why})
        witnessed += wit
    n = len(env.d.arrows)
    by_kind = {k: sum(1 for a in env.d.arrows if a.kind == k) for k in ("same", "next", "cdc")}
    return {"ok": not fails, "n": n, "by_kind": by_kind, "witnessed": witnessed,
            "evidence": evidence, "fsm_guard_checked": env.fsms is not None,
            "failures": fails[:10], "n_failed": len(fails)}


def _fsm_guard(env: _Env, a) -> tuple[str | None, str]:
    """(failure or None, evidence class) for an arrow that passed the structural tests."""
    if a.kind == "same":
        return None, "comb"
    if a.kind == "cdc":
        return None, "cdc"
    if env.fsms is None:
        return None, "structural"
    dom = env.lanes[a.src.lane][1]
    for i, k in enumerate(a.path[1:], 1):
        if k not in env.fsms or not env.hier(k) or not env.vcd.has(env.hier(k)):
            continue
        enum, trans = env.fsms[k]
        e = env.edges[dom]
        sa = enum.get(env.vcd.at(env.hier(k), e[a.src.cycle]))
        sb = enum.get(env.vcd.at(env.hier(k), e[a.dst.cycle]))
        conds = [c for s, t, c in trans if t == sb and s in (sa, "*")] if sa and sb else []
        if not conds:
            return None, "structural"  # transition unknown to fsm_ext
        reads = {x for c in conds for x in _IDENT.findall(c)}
        names = {env.graph["nodes"].get(p, {}).get("name") for p in a.path[:i]}
        names |= {p[len(env.inst) + 1:] for p in a.path[:i]}
        if not reads & names:
            return f"path crosses FSM {k} ({sa}->{sb}) but its guard {conds} reads no path node", ""
        return None, "fsm_guard"
    return None, "structural"


def _arrow(env: _Env, a, hop) -> tuple[str | None, int]:
    nodes = env.graph["nodes"]
    (ls, ds), (ld, dd) = env.lanes[a.src.lane], env.lanes[a.dst.lane]
    if a.path[0] != f"{env.inst}.{ls.signal}" or a.path[-1] != f"{env.inst}.{ld.signal}":
        return "path ends are not the lanes' graph nodes", 0
    lines: set[int] = set()
    for u, v in zip(a.path, a.path[1:], strict=False):
        vias = hop.get((u, v))
        if not vias:
            return f"no DATA/CONTROL/ADDR/PORT edge {u} -> {v}", 0
        lines |= {int(m.group(1)) for x in vias if (m := _VIA_LINE.search(x))}
    regs = sum(1 for k in a.path[1:] if nodes.get(k, {}).get("is_state"))
    if regs != a.regs:
        return f"path has {regs} register(s), arrow says {a.regs}", 0
    es, ed = env.edges[ds], env.edges[dd]
    if es[a.src.cycle] != a.src.t or ed[a.dst.cycle] != a.dst.t:
        return "end time is not the posedge of its cycle", 0
    if a.kind == "same" and not (ds == dd and regs == 0 and a.dst.cycle == a.src.cycle):
        return "same-cycle arrow with offset/domain/register mismatch", 0
    if a.kind == "next" and not (ds == dd and regs == 1 and a.dst.cycle == a.src.cycle + 1):
        return "next-cycle arrow with offset/domain/register mismatch", 0
    if a.kind == "cdc":
        ra = _register_pair(env, a.path, ds, dd)
        if not (ds != dd and regs >= 1 and a.dst.t > a.src.t and ra is not None):
            return "cdc arrow within one domain, without a register pair, or backwards", 0
        if a.dst.cycle != _cdc_cycle(es, ed, a.src.cycle, ra, regs - ra):
            return "cdc destination cycle does not follow the register pair timing", 0
    if not env.changed(env.name(ls.signal), ds, a.src.cycle):
        return f"{ls.signal} does not change at cycle {a.src.cycle}", 0
    if not env.changed(env.name(ld.signal), dd, a.dst.cycle):
        return f"{ld.signal} does not change at cycle {a.dst.cycle}", 0
    if any(s.line not in lines for s in a.via_lines):
        return "via line not on the path's edges", 0
    return None, int(_witnessed(env, a, ds))


def _cdc_cycle(ea: list[int], eb: list[int], c: int, ra: int, rb: int) -> int:
    """Sampled semantics: last A register updates at ea[c-1+ra], first B register at the next
    B edge k0, the destination shows at B cycle k0+rb."""
    i = min(max(c - 1 + ra, 0), len(ea) - 1)
    return next((k for k, t in enumerate(eb) if t > ea[i]), len(eb)) + rb


def _register_pair(env: _Env, path: list[str], da: str, db: str) -> int | None:
    """Registers on the path (ends included) are domain-A ones then domain-B ones, >= 1 each.
    Returns the number of domain-A registers after the source, None when not a pair."""
    if "regdom" not in env.__dict__:
        env.regdom = _register_domains(env.graph, {c["port"]: c["domain"]
                                                   for c in env.sim.get("clocks", [])})
    doms = [env.regdom.get(k) for k in path if env.graph["nodes"].get(k, {}).get("is_state")]
    na = next((i for i, d in enumerate(doms) if d != da), len(doms))
    if not (na >= 1 and na < len(doms) and all(d == db for d in doms[na:])):
        return None
    src_reg = bool(env.graph["nodes"].get(path[0], {}).get("is_state"))
    return na - 1 if src_reg else na


def _register_domains(graph: dict, port2dom: dict[str, str]) -> dict[str, str]:
    """Register -> domain: CLOCK-edge source traced back <= 3 DATA/PORT driver hops to a clock
    port of sim.json (independent re-implementation of timing_bridge.register_domains)."""
    drv: dict[str, set[str]] = {}
    for e in graph["edges"]:
        if e["type"] in ("DATA", "PORT"):
            drv.setdefault(e["dst"], set()).add(e["src"])
    out: dict[str, str] = {}
    for e in graph["edges"]:
        if e["type"] != "CLOCK":
            continue
        front, seen, doms = {e["src"]}, {e["src"]}, set()
        for _ in range(4):
            doms = {port2dom[n_] for n in front
                    if (n_ := graph["nodes"].get(n, {}).get("name")) in port2dom}
            if doms:
                break
            front = {s for n in front for s in drv.get(n, ())} - seen
            seen |= front
        if len(doms) == 1:
            out.setdefault(e["dst"], doms.pop())
    return out


def _witnessed(env: _Env, a, dom: str) -> bool:
    r = 0
    for k in a.path[1:-1]:
        r += 1 if env.graph["nodes"].get(k, {}).get("is_state") else 0
        name = env.hier(k)
        if name is None or not env.vcd.has(name) or (a.kind == "cdc" and r > 0):
            continue
        if not env.changed(name, dom, a.src.cycle + r):
            return False
    return True


# ---- T3 -----------------------------------------------------------------------------------
def _accounting(env: _Env) -> dict:
    d = env.d
    lo, hi = min(w.t0 for w in d.windows), max(w.t1 for w in d.windows)
    per, ok = {}, True
    inside = [g for g in d.gaps if any(w.t0 <= g.after_t and g.until_t <= w.t1 for w in d.windows)]
    outside = len(d.gaps) - len(inside)
    for dm in d.domains:
        e = env.edges[dm.id]
        span = [i for i, t in enumerate(e) if lo <= t <= hi]
        cyc = [{s.cycle for s in ln.values} for ln in dm.lanes]
        drawn = cyc[0] if cyc else set()
        same = all(c == drawn for c in cyc)
        expect = {i for i in span if not any(g.after_t < e[i] < g.until_t for g in d.gaps)}
        gap_n = sum(g.cycles.get(dm.id, 0) for g in d.gaps)
        true_gap = [sum(1 for t in e if g.after_t < t < g.until_t) for g in d.gaps]
        row = {"drawn": len(drawn), "gaps": gap_n, "total": len(span),
               "lanes_share_cycles": same, "drawn_is_outside_gaps": drawn == expect,
               "gap_counts_exact": gap_n == sum(true_gap)}
        row["ok"] = (len(drawn) + gap_n == len(span) and same and drawn == expect
                     and row["gap_counts_exact"])
        ok &= row["ok"]
        per[dm.id] = row
    hidden = _hidden_changes(env, d.gaps)
    fast = min(d.domains, key=lambda dm: dm.period).id if d.domains else None
    n_lanes = sum(len(dm.lanes) for dm in d.domains)
    caps = {"lanes": n_lanes, "lanes_ok": n_lanes <= MAX_LANES,
            "fast_cycles": per.get(fast, {}).get("drawn", 0),
            "fast_cycles_ok": per.get(fast, {}).get("drawn", 0) <= MAX_CYCLES}
    simp_gaps = sum(1 for s in d.simplifications if s.what.startswith("gap "))
    return {"ok": bool(ok and hidden == 0 and outside == 0 and caps["lanes_ok"]
                       and caps["fast_cycles_ok"] and simp_gaps == len(d.gaps)),
            "domains": per, "gaps": len(d.gaps), "gaps_outside_windows": outside,
            "gap_hidden_changes": hidden, "gaps_recorded": simp_gaps, "caps": caps}


def _hidden_changes(env: _Env, gaps) -> int:
    n = 0
    for ln, dom in env.lanes.values():
        name = env.name(ln.signal)
        if not env.vcd.has(name):
            continue
        e = env.edges[dom]
        for i in range(1, len(e)):
            if any(g.after_t < e[i] < g.until_t for g in gaps) and env.changed(name, dom, i):
                n += 1
    return n


def _find(p: str) -> Path:
    for cand in (Path(p), ROOT / p):
        if cand.is_file():
            return cand
    raise FileNotFoundError(p)


def main(argv: list[str]) -> int:
    fx = None
    if "--fsm-ext" in argv:
        i = argv.index("--fsm-ext")
        fx = json.loads(Path(argv[i + 1]).read_text())
        argv = argv[:i] + argv[i + 2:]
    if len(argv) < 3:
        print(__doc__)
        return 2
    d = ts.TimingDiagram.model_validate_json(Path(argv[0]).read_text())
    graph = json.loads(Path(argv[1]).read_text())
    sim = json.loads(Path(argv[2]).read_text())
    vcd = vcdmod.parse(_find(argv[3] if len(argv) > 3 else sim["vcd"]))
    res = check(d, vcd, graph, sim, fx)
    print(json.dumps(res, indent=1))
    return 0 if all(v.get("ok") for v in res.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
