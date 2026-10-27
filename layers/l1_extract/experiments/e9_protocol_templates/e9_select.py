"""e9: boundary-port protocol templates, clock domains and lanes -> signals.json (top module).

    uv run --package rtl2d-l1 python \
        layers/l1_extract/experiments/e9_protocol_templates/e9_select.py \
        --files F... --top T [--name N] [--include-dir D...] [--define D...] [--out DIR]

Writes DIR/signals.json (default DIR = runs/e9_protocol_templates/<name>) and prints a summary.

Library use (x4 loads this file through x4_tools.load):
    signals = select(run)   # run = annotate_design(..., cfg=RunConfig(mode="heuristic",
                            #       targets=frozenset({"block", "fsm", "timing"})))
Format: pipeline/experiments/x4_fsm_timing/FORMATS.md, `signals.json`. One extra key, `notes`,
lists every simplification/assumption made on the data (with reasons and lines).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
MAX_INTERNAL = 4
INTERNAL_HOPS = 2  # register hops: combinational nets on the way are free (e9_graph)


def _bootstrap_graph():
    """Load e9_graph.py once (no sys.path); its `sibling()` then loads the other e9 files."""
    if "e9_graph" not in sys.modules:
        spec = importlib.util.spec_from_file_location("e9_graph", HERE / "e9_graph.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["e9_graph"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["e9_graph"]


gm = _bootstrap_graph()
cd = gm.sibling("clock_domains")
tp = gm.sibling("templates")


def _top(run) -> str:
    G = run.graph
    if len(G.tops) != 1:
        raise ValueError(f"expected exactly one top instance, got {G.tops}")
    return G.tops[0]


def _members(G, dom, it) -> list[dict]:
    out = []
    for k, role in it.members:
        n = G.nodes[k]
        d, _how = dom.port_domain(k)
        out.append({"port": n.name, "role": role, "width": n.width, "dir": n.port_dir,
                    "domain": d, "line": n.line})
    return out


def _iface_domain(members: list[dict]) -> str | None:
    ds = {m["domain"] for m in members if m["domain"]}
    if "cdc" in ds or len(ds) > 1:
        return "cdc"
    return next(iter(ds), None)


def _heuristic_notes(run, G, top_mod: str, ifaces) -> list[str]:
    """Compare L1's prefix bundles (hints only) with the structural interfaces."""
    res = run.results_full.get(top_mod)
    table = run.tables_by_module.get(top_mod)
    if res is None or table is None:
        return []
    by_id = table.by_id()
    ours = [{G.nodes[k].name for k, _r in i.members} for i in ifaces if i.protocol != "SIMPLE"]
    notes = []
    for b in res.interfaces:
        if b.protocol.value in ("CLOCK_RESET", "SIMPLE"):
            continue
        names = frozenset(by_id[x].name for x in b.member_ids if x in by_id)
        hs = sorted(n for n in names if tp.port_class(n))
        if not hs:
            continue
        same = any(set(hs) <= s for s in ours)
        notes.append(
            f"L1 prefix bundle '{b.name}' ({b.protocol.value}) handshake ports {hs}: "
            + ("same pairing as a structural interface" if same
               else "NOT followed (structural pairing differs)")
        )
    return notes


def _internal(run, G, top, dom, ifaces, cr) -> tuple[list[dict], list[dict], list[str]]:
    """Internal lanes: FSM state registers of the top always; other top registers within
    INTERNAL_HOPS of a (non-SIMPLE) interface member, picked round-robin over interfaces by
    distance (then line) up to MAX_INTERNAL; everything else goes to `dropped` with reason."""
    notes: list[str] = []
    dropped: list[dict] = []
    hs = [i for i in ifaces if i.protocol != "SIMPLE"]
    near_of: dict[str, dict[str, tuple[int, str]]] = {}  # reg -> {iface: (dist, member)}
    for it in hs:
        dist = gm.reg_distances(G, [k for k, _r in it.members], top, INTERNAL_HOPS,
                                skip=frozenset(cr))
        for k, d in dist.items():
            near_of.setdefault(k, {})[it.name] = d
    any_dist = gm.reg_distances(G, [k for i in hs for k, _r in i.members], top,
                                INTERNAL_HOPS + 1, skip=frozenset(cr))
    fsm_keys = {}
    for f in run.fsms:
        k = f"{f.instance}.{f.state}"
        if k not in G.nodes:
            notes.append(f"FSM {f.module}.{f.state}: no graph node {k}; not added as lane")
        elif G.nodes[k].inst != top:
            dropped.append({"signal": k, "line": G.nodes[k].line,
                            "reason": f"FSM state register in submodule {f.instance} "
                                      "(top module only)"})
        else:
            fsm_keys[k] = f
    loops = sorted(k for k, n in G.nodes.items()
                   if n.inst == top and n.is_state and n.port_dir is None
                   and not n.loop_var and gm.is_loop_index(G, k))
    for k in loops:
        notes.append(f"{G.nodes[k].rel} (line {G.nodes[k].line}, {G.nodes[k].type_str}): "
                     "for-loop index reported as a register by L1; not a lane candidate")
    regs = sorted(
        (k for k, n in G.nodes.items()
         if n.inst == top and n.is_state and n.port_dir is None and not n.loop_var
         and k not in fsm_keys and k not in loops),
        key=lambda k: (G.nodes[k].line, G.nodes[k].offset, k),
    )
    queues: dict[str, list] = {i.name: [] for i in hs}
    for k in regs:
        n = G.nodes[k]
        if n.depth is not None:
            dropped.append({"signal": n.rel, "line": n.line, "reason": f"memory (depth {n.depth})"})
            continue
        if not hs:
            dropped.append({"signal": n.rel, "line": n.line,
                            "reason": "no confirmed-or-candidate interface in the design to be "
                                      "near (only FSM state registers become lanes)"})
            continue
        if k not in near_of:
            d = any_dist.get(k)
            far = f"{d[0] if d else f'more than {INTERNAL_HOPS + 1}'} register hops"
            dropped.append({"signal": n.rel, "line": n.line,
                            "reason": f"{far} from every interface member (limit "
                                      f"{INTERNAL_HOPS})"})
            continue
        for name, d in sorted(near_of[k].items()):
            queues[name].append((d[0], n.line, k))
    for q in queues.values():
        q.sort()
    chosen: list[str] = []
    while len(chosen) < MAX_INTERNAL and any(queues.values()):
        for name in sorted(queues):
            q = queues[name]
            while q and q[0][2] in chosen:
                q.pop(0)
            if q and len(chosen) < MAX_INTERNAL:
                chosen.append(q.pop(0)[2])
    internal = []
    for k in chosen:
        n = G.nodes[k]
        dist, why = min((d[0], f"{d[0]} register hop(s) from {G.nodes[d[1]].name}")
                        for d in near_of[k].values())
        internal.append({"signal": n.rel, "key": k, "width": n.width,
                         "domain": dom.reg_domain.get(k), "role": "reg", "line": n.line,
                         "near": [f"if.{x}" for x in sorted(near_of[k])], "reason": why})
    for k in regs:
        n = G.nodes[k]
        if k in near_of and k not in chosen and n.depth is None:
            d = min(near_of[k].values())
            dropped.append({"signal": n.rel, "line": n.line,
                            "reason": f"{d[0]} register hop(s) from {G.nodes[d[1]].name}, "
                                      f"beyond cap {MAX_INTERNAL} (round-robin over "
                                      "interfaces by distance, then line)"})
    for k, f in fsm_keys.items():
        n = G.nodes[k]
        near = near_of.get(k, {})
        internal.append({"signal": n.rel, "key": k, "width": n.width,
                         "domain": dom.reg_domain.get(k), "role": "state", "line": n.line,
                         "near": [f"if.{x}" for x in sorted(near)],
                         "reason": f"FSM state register (semantic_check="
                                   f"{getattr(f, 'semantic_check', None)})"})
    return internal, dropped, notes


def _submodule_drops(G, top) -> list[dict]:
    out = []
    for p in sorted(G.instances, key=lambda p: (G.instances[p].line, p)):
        info = G.instances[p]
        if info.parent != top:
            continue
        nreg = sum(1 for n in G.nodes.values()
                   if n.is_state and (n.inst == p or n.inst.startswith(p + ".")))
        out.append({"signal": p, "line": info.line,
                    "reason": f"submodule instance of {info.module}: {nreg} register(s) not "
                              "considered as lanes (top module only)"})
    return out


def select(run, design: str | None = None, notes: bool = True) -> dict:
    """signals.json dict (FORMATS.md) for the top module of an L1 heuristic DesignRun.

    With notes=True (default) the dict carries one key beyond FORMATS.md, `notes`
    (simplifications/assumptions); notes=False returns exactly the FORMATS.md keys."""
    G = run.graph
    top = _top(run)
    top_mod = G.instances[top].module
    dom = cd.Domains(G, top)
    clocks = dom.clocks()
    resets = dom.resets()
    cr_ports = {k for k, n in G.nodes.items() if n.inst == top and n.port_dir == "in"
                and (n.name in {c["port"] for c in clocks} | {r["port"] for r in resets})}
    m = tp.Matcher(G, top, dom.cr_nets, cr_ports)
    ifaces = sorted(m.run(), key=lambda i: (min(G.nodes[k].line for k, _r in i.members),
                                            i.name))
    notes_out = list(dom.notes) + list(m.notes)
    out_ifaces = []
    for it in ifaces:
        members = _members(G, dom, it)
        idom = _iface_domain(members)
        for (k, _r), mem in zip(it.members, members, strict=True):
            d, how = dom.port_domain(k)
            if d is None and idom and idom != "cdc":
                mem["domain"] = idom
                how += f"; inherited {idom} from the other members of if.{it.name}"
            if "assumed" in how or "inherited" in how or d is None:
                notes_out.append(f"domain of {G.nodes[k].name} (line {G.nodes[k].line}): {how}")
        out_ifaces.append({
            "id": f"if.{it.name}", "name": it.name, "protocol": it.protocol,
            "direction": it.direction, "domain": _iface_domain(members),
            "confirmed": it.confirmed, "members": members, "evidence": it.evidence,
            "demoted_reason": it.demoted_reason,
        })
    internal, dropped, n2 = _internal(run, G, top, dom, ifaces, dom.cr_nets)
    notes_out += n2
    other, extra_drop = _others(G, top, m, cr_ports, dom, notes_out)
    notes_out += _heuristic_notes(run, G, top_mod, ifaces)
    return {
        "design": design or run.design.name, "top": top_mod,
        "clocks": clocks, "resets": resets, "interfaces": out_ifaces,
        "internal": internal, "other_inputs": other,
        "dropped": dropped + extra_drop + _submodule_drops(G, top),
        **({"notes": notes_out} if notes else {}),
    }


def _others(G, top, m, cr_ports, dom, notes) -> tuple[list[dict], list[dict]]:
    other, drop = [], []
    for k in m.ports:
        n = G.nodes[k]
        if k in m.claimed or k in cr_ports:
            continue
        d, how = dom.port_domain(k)
        if "assumed" in how or d is None:
            notes.append(f"domain of {n.name} (line {n.line}): {how}")
        if n.port_dir == "in":
            other.append({"port": n.name, "width": n.width, "domain": d, "line": n.line,
                          "kind": _input_kind(G, m, k, notes)})
        else:
            why = "status name" if tp.STATUS_RE.search(n.name) else "no template slot"
            if not m.back(k):
                why += ("; combinational from inputs only (no register drives it)"
                        if G.preds(k, set(gm.FLOW))
                        else "; undriven (constant or parameter-disabled)")
            drop.append({"signal": n.name, "line": n.line,
                         "reason": f"output port in no interface ({why})"})
    for _k, n in sorted(G.nodes.items()):
        if n.inst == top and n.port_dir == "inout":
            drop.append({"signal": n.name, "line": n.line, "reason": "inout port (unsupported)"})
    return other, drop


def _input_kind(G, m, k, notes: list[str]) -> str:
    """control: 1-bit, or multi-bit that only gates registers (CONTROL paths, e.g. a mode
    select); data: any other multi-bit input (default when it reaches no register)."""
    n = G.nodes[k]
    if n.width == 1:
        return "control"
    regs = m.fwd(k)
    if regs and not gm.data_only(regs):
        return "control"
    if not regs:
        notes.append(f"{n.name} (line {n.line}, {n.width} bits): reaches no register; kind "
                     "'data' by default for a multi-bit input")
    return "data"


def summarize(sig: dict) -> str:
    lines = [f"{sig['design']} (top {sig['top']})"]
    lines.append("  clocks: " + ", ".join(f"{c['port']}[{c['edge']}]" for c in sig["clocks"]))
    lines.append("  resets: " + ", ".join(
        f"{r['port']}(low={r['active_low']},sync={r['sync']},{'/'.join(r['domains'])})"
        for r in sig["resets"]))
    for i in sig["interfaces"]:
        mem = ", ".join(f"{x['port']}:{x['role']}" for x in i["members"])
        flag = "confirmed" if i["confirmed"] else f"UNCONFIRMED ({i['demoted_reason'] or ''})"
        lines.append(f"  {i['id']} {i['protocol']} {i['direction']} {i['domain']} {flag}: {mem}")
    lines.append("  internal: " + ", ".join(f"{x['signal']}({x['role']})"
                                              for x in sig["internal"]))
    lines.append("  other_inputs: " + ", ".join(f"{x['port']}({x['kind']})"
                                                  for x in sig["other_inputs"]))
    lines.append(f"  dropped: {len(sig['dropped'])}  notes: {len(sig['notes'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from rtl2d_l1.pipeline import RunConfig, annotate_design

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", nargs="+", required=True)
    ap.add_argument("--top", required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--include-dir", nargs="*", default=[])
    ap.add_argument("--define", nargs="*", default=[])
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    name = a.name or a.top
    cfg = RunConfig(mode="heuristic", targets=frozenset({"block", "fsm", "timing"}))
    run = annotate_design(a.files, top=a.top, include_dirs=a.include_dir, defines=a.define,
                          cfg=cfg, name=name)
    sig = select(run, design=name)
    out = Path(a.out) if a.out else ROOT / "runs" / "e9_protocol_templates" / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "signals.json").write_text(json.dumps(sig, indent=1) + "\n", encoding="utf-8")
    print(summarize(sig))
    print(f"wrote {out / 'signals.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
