"""L1 (Stage 1) output -> L3 experiment input (e0 diagram.json + hints).

A stand-in for L2, for integration experiments only. Everything is derived from the RTL by L1's
front end (instances, ports, port connections, state, memories) plus L1's teacher labels where
they exist; nothing is hand-written per design.

Hierarchical mode (this file): blocks = child instances of the top module.
  * kind    : memory | pipeline_reg | register | mux | alu | adder | control | split | comb,
              from the child's structure (memories, state, select inputs, arithmetic) and, if
              present, the teacher's roles for that module.
  * nets    : one per driving port, followed through top-level wiring; a sink that reads only a
              slice of a bus is fed through a `split` block (the bus fields).
  * hints   : stage_boundary for pipeline registers (ordered along the data flow), stage_index
              for everything else = min over its drivers (0 for non-pipeline sources), lane
              control for control-only units, flow_role feedback for sinks in an earlier stage.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

L1_DIR = Path(__file__).resolve().parents[3] / "layers" / "l1_extract"
sys.path.insert(0, str(L1_DIR / "src"))

from rtl2d_l1.frontend.graph import EdgeType  # noqa: E402
from rtl2d_l1.llm.teacher import TeacherConfig  # noqa: E402
from rtl2d_l1.pipeline import RunConfig, annotate_design  # noqa: E402
from rtl2d_l1.store import RunStore  # noqa: E402

SCHEMA_VERSION = "0.1.0"  # e0 experiment-local format (docs/adr/0002-diagram-minimal-core.md)
FLOW = {EdgeType.DATA, EdgeType.CONTROL, EdgeType.ADDR}
CTRL_KINDS = {"control"}


def _sid(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", s)


def nice_label(inst_name: str, kind: str) -> str:
    """u_fwd_a_mux -> 'FWD A MUX', u_if_id -> 'IF/ID' (pipeline registers)."""
    base = re.sub(r"^(u|i|inst)_", "", inst_name)
    toks = [t for t in base.split("_") if t]
    if kind == "pipeline_reg" and len(toks) == 2:
        return "/".join(t.upper() for t in toks)
    words = []
    for t in toks:
        words.append(t.upper() if len(t) <= 4 else t.capitalize())
    return " ".join(words) or inst_name


# ------------------------------------------------------------------ classification
def classify(G, inst_path: str, result=None) -> str:
    """Shape class of a child instance from its structure (and teacher roles if any)."""
    info = G.instances[inst_path]
    nodes = [
        n for n in G.nodes.values() if n.inst == inst_path or n.inst.startswith(inst_path + ".")
    ]
    if any((n.depth or 0) >= 2 for n in nodes):
        return "memory"  # an actual array; a STORAGE role on a plain register is not enough
    outs = [info.ports[p] for p, d in info.port_dirs.items() if d == "out"]
    ins = [info.ports[p] for p, d in info.port_dirs.items() if d == "in"]
    state = [n for n in nodes if n.is_state]
    if state:
        # a register stage: most outputs are flops each loaded from one input (a lane)
        lanes = lanes_of(G, inst_path)
        if len(lanes) >= 3 and len(lanes) >= 0.6 * len(outs):
            return "pipeline_reg"
        return "register"
    arith = any(n.arith_srcs for n in nodes)
    if arith:
        if len(outs) > 1:
            return "comb"
        ctrl_in = [i for i in ins if G.nodes[i].width <= 4]
        return "alu" if ctrl_in else "adder"
    if len(outs) == 1:
        o = G.nodes[outs[0]]
        data_ins = [i for i in ins if G.nodes[i].width == o.width]
        sel = [i for i in ins if G.nodes[i].width < o.width]
        if (
            len(data_ins) >= 2
            and len(sel) == 1
            and 2 ** G.nodes[sel[0]].width >= len(data_ins)
            and len(data_ins) + 1 == len(ins)
        ):
            return "mux"
    narrow_out = sum(1 for o in outs if G.nodes[o].width <= 5)
    if outs and narrow_out / len(outs) >= 0.6:
        return "control"
    return "comb"


def lanes_of(G, inst_path: str) -> dict[str, str]:
    """Output port -> the one input port its flop loads from (through enables / muxes inside
    the instance). Structural, so it does not depend on port names."""
    info = G.instances[inst_path]
    ins = {info.ports[p]: p for p, d in info.port_dirs.items() if d == "in"}
    inside = inst_path + "."
    pairs = {}
    for po, d in info.port_dirs.items():
        if d != "out":
            continue
        o = info.ports[po]
        regs = (
            [o]
            if G.nodes[o].is_state
            else [s for s, et in G.preds(o) if et == EdgeType.DATA and G.nodes[s].is_state]
        )
        if len(regs) != 1:
            continue
        found, seen, frontier = set(), {regs[0]}, [regs[0]]
        for _ in range(4):
            nxt = []
            for k in frontier:
                for s, et in G.preds(k):
                    if et != EdgeType.DATA or s in seen:
                        continue
                    seen.add(s)
                    if s in ins:
                        found.add(ins[s])
                    elif G.nodes[s].inst.startswith(inside) or G.nodes[s].inst == inst_path:
                        if not G.nodes[s].is_state:
                            nxt.append(s)
            frontier = nxt
        if len(found) == 1:
            pairs[po] = next(iter(found))
    return pairs


# ------------------------------------------------------------------ connectivity
def _sync_class(G, key: str) -> str | None:
    """'clock' / 'reset' if the node drives a clock / reset within a few port hops."""
    frontier, seen = [key], {key}
    for _ in range(4):
        nxt = []
        for k in frontier:
            for t, et in G.succs(k):
                if et == EdgeType.CLOCK:
                    return "clock"
                if et == EdgeType.RESET:
                    return "reset"
                if et == EdgeType.PORT and t not in seen:
                    seen.add(t)
                    nxt.append(t)
        frontier = nxt
    return None


GROUP_SHAPE = {  # teacher GroupKind -> shape of a top-level logic block
    "CONTROLLER": "control",
    "ARBITER": "control",
    "DECODER": "control",
    "COUNTER_TIMER": "register",
    "MEMORY": "memory",
    "BUFFER": "memory",
    "REGISTER_BANK": "register",
    "PIPELINE_STAGE": "register",
}


def _is_logic(G, k: str) -> bool:
    """A top-level signal computed by logic at the top (a register, arithmetic, a select or
    condition, or a combination of several sources), not a wire that renames one source."""
    n = G.nodes[k]
    if n.is_state or n.arith_srcs:
        return True
    preds = [(s, et) for s, et in G.preds(k) if et not in (EdgeType.CLOCK, EdgeType.RESET)]
    if any(et in (EdgeType.CONTROL, EdgeType.ADDR) for _, et in preds):
        return True
    return len({s for s, _ in preds}) >= 2


def _port(pid, owner, direction, width, cls=None):
    return {
        "id": pid,
        "owner_block_id": owner,
        "direction": direction,
        "width": max(1, width),
        "class": cls,
    }


def build(design: dict, model: str = "claude-session", root: str | None = None) -> tuple:
    """One connectivity pass for hierarchical, flat and mixed tops.

    Blocks: every child instance of the top, plus one logic block per teacher group that owns
    top-level signals (flat designs only have these). Signals that belong to no block are
    wiring: nets are followed through them. A sink that reads a slice (or a different width)
    is fed by a `split` tap; a sink with several drivers is fed by a `join` block."""
    from rtl2d_l1.trace import entity_nodes

    cfg = RunConfig(
        mode="teacher",
        store_only=True,
        teacher=TeacherConfig(model=model, effort="session"),
    )
    run = annotate_design(
        design["files"], top=root or design["top"], cfg=cfg, store=RunStore(L1_DIR / "runs/store")
    )
    G = run.graph
    top = G.tops[0]
    tinfo = G.instances[top]
    # a wrapper (one child, no logic of its own) says nothing: draw the child instead
    while len(tinfo.children) == 1 and not any(
        n.inst == top and not n.port_dir and _is_logic(G, k) for k, n in G.nodes.items()
    ):
        child = G.instances[tinfo.children[0]].module
        run = annotate_design(
            design["files"], top=child, cfg=cfg, store=RunStore(L1_DIR / "runs/store")
        )
        G = run.graph
        top = G.tops[0]
        tinfo = G.instances[top]
    tmod = tinfo.module
    res_top = run.results_full.get(tmod)
    table = run.tables_by_module.get(tmod)

    blocks, ports = [], []
    kind_of, label_of = {}, {}
    owner: dict[str, str] = {}  # graph node -> block id (child ports, logic members)
    port_of: dict[str, str] = {}  # child port node / top port node -> port id
    inst_block: dict[str, str] = {}
    used_ids: set[str] = set()

    def new_id(base: str) -> str:
        i, bid = 1, base
        while bid in used_ids:
            i += 1
            bid = f"{base}_{i}"
        used_ids.add(bid)
        return bid

    for c in tinfo.children:
        ci = G.instances[c]
        bid = new_id(_sid("b." + c[len(top) + 1 :]))
        inst_block[c] = bid
        kind = classify(G, c, run.results_full.get(ci.module))
        kind_of[bid], label_of[bid] = kind, nice_label(ci.name, kind)
        blocks.append({"id": bid, "label": label_of[bid], "kind": kind, "parent_id": None})
        for pname, key in ci.ports.items():
            pid = _sid(f"{bid}.{pname}")
            port_of[key], owner[key] = pid, bid
            d = "input" if ci.port_dirs[pname] == "in" else "output"
            ports.append(_port(pid, bid, d, G.nodes[key].width))

    # logic blocks: teacher groups of the top that own top-level (non-port) signals
    logic_src: dict[str, list[str]] = {}
    if res_top is not None and table is not None:
        for g in res_top.groups:
            keys = []
            for eid in dict.fromkeys([*g.anchor_ids, *g.member_ids]):
                for k in entity_nodes(G, table, eid):
                    n = G.nodes[k]
                    if n.inst == top and not n.port_dir and k not in owner and _is_logic(G, k):
                        keys.append(k)
            if not keys:
                continue
            bid = new_id(_sid("b.g." + g.name))
            kind = GROUP_SHAPE.get(g.kind.value, "comb")
            kind_of[bid], label_of[bid] = kind, g.name.replace("_", " ")
            blocks.append({"id": bid, "label": label_of[bid], "kind": kind, "parent_id": None})
            for k in keys:
                owner[k] = bid
            logic_src[bid] = keys

    # logic no group claims joins the logic block it is most connected to (else it would stay
    # wiring and every sink it reaches would need a join block)
    changed = bool(logic_src)
    while changed:
        changed = False
        for k, n in G.nodes.items():
            if k in owner or n.inst != top or n.port_dir or not _is_logic(G, k):
                continue
            votes = defaultdict(int)
            for o, et in [*G.preds(k), *G.succs(k)]:
                b = owner.get(o)
                if b in logic_src and et not in (EdgeType.CLOCK, EdgeType.RESET):
                    votes[b] += 1
            if votes:
                b = max(sorted(votes), key=votes.get)
                owner[k] = b
                logic_src[b].append(k)
                changed = True
    # a top output computed by logic (`output reg x`) is driven by the block that computes it
    out_owner: dict[str, str] = {}
    for pname, key in tinfo.ports.items():
        if tinfo.port_dirs[pname] == "out" and _is_logic(G, key) and logic_src:
            votes = defaultdict(int)
            for o, et in G.preds(key):
                if owner.get(o) in logic_src and et not in (EdgeType.CLOCK, EdgeType.RESET):
                    votes[owner[o]] += 1
            if votes:
                out_owner[key] = max(sorted(votes), key=votes.get)
    # An output register whose drivers are all ports (spimemio_xfer's flash_csb is loaded from
    # din_valid / din_ready and read only by flash_clk, both ports) got no vote above; reach()
    # would then wire the input port straight to it, losing the register. Let it follow the
    # blocks of its neighbours, counting output ports already given a block, drivers first.
    rest = [key for pname, key in tinfo.ports.items() if tinfo.port_dirs[pname] == "out"
            and _is_logic(G, key) and logic_src and key not in out_owner]
    changed = True
    while rest and changed:
        changed = False
        for key in list(rest):
            for nbrs in (G.preds(key), G.succs(key)):
                votes = defaultdict(int)
                for o, et in nbrs:
                    b = owner.get(o) or out_owner.get(o)
                    if b in logic_src and et not in (EdgeType.CLOCK, EdgeType.RESET):
                        votes[b] += 1
                if votes:
                    out_owner[key] = max(sorted(votes), key=votes.get)
                    rest.remove(key)
                    changed = True
                    break

    for pname, key in tinfo.ports.items():
        d = tinfo.port_dirs[pname]
        pid = _sid(f"p.{pname}")
        port_of[key] = pid
        cls = _sync_class(G, key) if d == "in" else None
        ports.append(_port(pid, None, "input" if d == "in" else "output", G.nodes[key].width, cls))
    port_by_id = {p["id"]: p for p in ports}

    def is_out_port(t: str) -> bool:
        return t in port_of and port_by_id[port_of[t]]["direction"] == "output"

    ctrl_use: dict[str, set] = defaultdict(set)  # sink node -> {is it used as control}

    def used_as_control(t: str) -> bool:
        """A child input that only feeds conditions / selects inside the child is control."""
        if t not in port_of:
            return ctrl_use[t] == {True}
        uses = {et for _s, et in G.succs(t) if et not in (EdgeType.CLOCK, EdgeType.RESET)}
        return bool(uses) and uses <= {EdgeType.CONTROL}

    # ---- phase A: (source port, sink) edges through unowned top-level wiring
    def reach(start: str, src_block: str | None) -> list[tuple]:
        """-> [(sink node, whole, via)]; sinks = nodes owned by other blocks, top outputs."""
        out, seen, stack = [], {start}, [(start, True, None)]
        while stack:
            k, whole, via = stack.pop()
            for t, et in G.succs(k):
                if et in (EdgeType.CLOCK, EdgeType.RESET) or t in seen:
                    continue
                seen.add(t)
                part = whole and not (et == EdgeType.DATA and G.is_partial(k, t))
                n = G.nodes[t]
                ob = owner.get(t)
                if ob is not None:
                    if ob != src_block and not (is_out_port(t) and n.inst != top):
                        out.append((t, part, via))
                        if t not in port_of:  # logic member: used as the edge says
                            ctrl_use[t].add(et == EdgeType.CONTROL)
                    continue
                if n.inst != top:
                    continue
                if n.port_dir == "out":
                    out.append((t, part, via))
                    continue
                if n.port_dir == "in":
                    continue
                stack.append((t, part, via if (via or part) else t))
        return out

    sources: list[tuple] = []  # (port id or None for logic members, block, starts, width)
    for c, bid in inst_block.items():
        ci = G.instances[c]
        for pname, key in ci.ports.items():
            if ci.port_dirs[pname] == "out":
                starts = [t for t, et in G.succs(key) if et == EdgeType.PORT]
                if starts:
                    sources.append((port_of[key], bid, starts, G.nodes[key].width))
    for bid, keys in logic_src.items():
        for k in keys:
            sources.append((None, bid, [k], G.nodes[k].width))
    for pname, key in tinfo.ports.items():
        if tinfo.port_dirs[pname] == "in":
            sources.append((port_of[key], None, [key], G.nodes[key].width))

    edges = []  # (src pid, src width, sink pid, whole, field name)
    ctrl_ports: set[str] = set()
    seen_e: set[tuple] = set()
    for pid, bid, starts, w in sources:
        w = max(1, w)
        sinks: dict[str, tuple] = {}
        for s in starts:
            if pid is not None and G.nodes[s].inst == top and G.nodes[s].port_dir == "out":
                sinks.setdefault(s, (True, None))  # child output wired straight to a top output
            for t, whole, via in reach(s, bid):
                sinks.setdefault(t, (whole, via))
        if not sinks:
            continue
        if pid is None:  # logic member: one output port per signal that leaves the block
            pid = new_id(_sid(f"{bid}.{G.nodes[starts[0]].name}"))
            ports.append(_port(pid, bid, "output", w))
            port_by_id[pid] = ports[-1]
        for t, (whole, via) in sinks.items():
            if t in port_of:
                tp = port_of[t]
            else:  # a logic block member: one input port per arriving signal
                ob = owner[t]
                tp = _sid(f"{ob}.in.{pid.split('.', 1)[-1]}")
                if tp not in port_by_id:
                    ports.append(_port(tp, ob, "input", w))
                    port_by_id[tp] = ports[-1]
                whole = True
            if tp == pid or (pid, tp) in seen_e:
                continue
            seen_e.add((pid, tp))
            fname = G.nodes[via].name if via else None
            edges.append((pid, w, tp, whole and port_by_id[tp]["width"] == w, fname))
            if used_as_control(t):
                ctrl_ports.add(tp)
    for key, b in out_owner.items():
        tp = port_of[key]
        keep = [e for e in edges if e[2] == tp and port_by_id[e[0]]["owner_block_id"] == b]
        if not keep:
            pw = port_by_id[tp]["width"]
            sp = new_id(_sid(f"{b}.{G.nodes[key].name}"))
            ports.append(_port(sp, b, "output", pw))
            port_by_id[sp] = ports[-1]
            keep = [(sp, pw, tp, True, None)]
        edges = [e for e in edges if e[2] != tp] + keep[:1]

    # ---- phase B: nets, join blocks for multi-driver sinks, split taps for slices
    nets = []
    by_sink = defaultdict(list)
    for e in edges:
        by_sink[e[2]].append(e)
    remap = {}  # (src, sink) -> join input port
    for sink, es in by_sink.items():
        if len(es) < 2:
            continue
        jb = new_id(_sid(f"b.join.{sink}"))
        kind_of[jb], label_of[jb] = "split", "join"
        blocks.append({"id": jb, "label": "join", "kind": "split", "parent_id": None})
        jo = f"{jb}.out"
        sw = port_by_id[sink]["width"]
        ports.append(_port(jo, jb, "output", sw))
        port_by_id[jo] = ports[-1]
        nets.append(
            {"id": _sid(f"n.{jo}"), "source": jo, "targets": [sink], "width": sw, "class": None}
        )
        for j, (src, w, _t, _wh, _f) in enumerate(es):
            ji = f"{jb}.in{j}"
            ports.append(_port(ji, jb, "input", w))
            port_by_id[ji] = ports[-1]
            remap[(src, sink)] = ji
    by_src = defaultdict(list)
    for src, w, sink, whole, fname in edges:
        sink2 = remap.get((src, sink), sink)
        by_src[src].append((w, sink2, whole or sink2 != sink, fname))
    for src, es in by_src.items():
        w = es[0][0]
        whole = sorted({s for _w, s, wh, _f in es if wh})
        part = [(s, f) for _w, s, wh, f in es if not wh]
        if part:
            sb = new_id(_sid(f"b.fields.{src}"))
            kind_of[sb], label_of[sb] = "split", "fields"
            blocks.append({"id": sb, "label": "fields", "kind": "split", "parent_id": None})
            ip = f"{sb}.in"
            ports.append(_port(ip, sb, "input", w))
            port_by_id[ip] = ports[-1]
            whole.append(ip)
            taps = defaultdict(list)
            for s, f in part:
                taps[(f or s.rsplit(".", 1)[-1], port_by_id[s]["width"])].append(s)
            names = defaultdict(int)
            for f, _tw in taps:
                names[f] += 1
            for (f, tw), ss in sorted(taps.items()):
                op = new_id(_sid(f"{sb}.{f}" if names[f] == 1 else f"{sb}.{f}_{tw}"))
                ports.append(_port(op, sb, "output", tw))
                port_by_id[op] = ports[-1]
                nets.append(
                    {
                        "id": _sid(f"n.{op}"),
                        "source": op,
                        "targets": sorted(ss),
                        "width": tw,
                        "class": None,
                    }
                )
        if whole:
            nets.append(
                {
                    "id": _sid(f"n.{src}"),
                    "source": src,
                    "targets": sorted(whole),
                    "width": w,
                    "class": port_by_id[src]["class"],
                }
            )
    for n in nets:
        if n["class"] is None:
            # control = every sink uses it as a condition / select, or a control unit drives it
            ob = port_by_id[n["source"]]["owner_block_id"] or ""
            ctrl = all(t in ctrl_ports for t in n["targets"])
            n["class"] = "control" if (ctrl or kind_of.get(ob) in CTRL_KINDS) else "data"
        for pid in [n["source"], *n["targets"]]:
            if port_by_id[pid]["class"] is None:
                port_by_id[pid]["class"] = n["class"]

    diagram = {"schema_version": SCHEMA_VERSION, "blocks": blocks, "ports": ports, "nets": nets}
    hints = stage_hints(diagram, kind_of)
    meta = {
        "design": design["name"],
        "top": top,
        "kinds": kind_of,
        "labels": label_of,
        "teacher_groups": _teacher_groups(run, top, inst_block),
        "lanes": {
            bid: {_sid(f"{bid}.{o}"): _sid(f"{bid}.{i}") for o, i in lanes_of(G, c).items()}
            for c, bid in inst_block.items()
            if kind_of[bid] == "pipeline_reg"
        },
        "interfaces": _interfaces(run, top, port_of),
        "paths": {bid: c for c, bid in inst_block.items()},
    }
    diagram, hints, meta = fold_arrays(diagram, hints, meta)
    meta["view"] = choose_view(meta)
    return diagram, hints, meta


# ------------------------------------------------------------------ generate arrays (R13)
def fold_arrays(diagram: dict, hints: dict, meta: dict) -> tuple[dict, dict, dict]:
    """Instances that differ only in a generate index (s_ifaces[0].adapter, s_ifaces[1].adapter)
    become one block drawn once with a count, as papers draw them (one unit, x N).

    Every id that mentions a member (its ports, the join / fields blocks made for its sinks)
    is rewritten onto the representative, duplicates merge, nets merge by source. A join whose
    inputs all collapsed onto one source is bypassed when widths agree, else kept as a concat."""
    paths = meta.get("paths", {})
    key_of = defaultdict(list)
    for bid, path in paths.items():
        key_of[re.sub(r"\[\d+\]", "[*]", path)].append(bid)
    subs, count = {}, {}
    for bids in key_of.values():
        if len(bids) < 2:
            continue
        r = sorted(bids)[0]
        count[r] = len(bids)
        for b in bids:
            if b != r:
                subs[b] = r
    meta = {**meta, "count": count}
    if not subs:
        return diagram, hints, meta
    keys = sorted(subs, key=len, reverse=True)

    def f(i: str) -> str:
        for k in keys:
            if k in i:
                i = i.replace(k, subs[k])
        return i

    blocks, seen = [], set()
    for b in diagram["blocks"]:
        nid = f(b["id"])
        if nid not in seen:
            seen.add(nid)
            blocks.append(
                {**b, "id": nid, "parent_id": f(b["parent_id"]) if b["parent_id"] else None}
            )
    ports, seen = [], set()
    for p in diagram["ports"]:
        nid = f(p["id"])
        if nid not in seen:
            seen.add(nid)
            ports.append(
                {
                    **p,
                    "id": nid,
                    "owner_block_id": f(p["owner_block_id"]) if p["owner_block_id"] else None,
                }
            )
    merged: dict[str, dict] = {}
    for n in diagram["nets"]:
        src = f(n["source"])
        ts = {f(t) for t in n["targets"]} - {src}
        if not ts:
            continue
        m = merged.setdefault(src, {**n, "source": src, "targets": set()})
        m["targets"] |= ts
        if n["class"] == "data":
            m["class"] = "data"
    nets = [
        {**m, "id": _sid(f"n.{src}"), "targets": sorted(m["targets"])} for src, m in merged.items()
    ]
    kinds = {
        b["id"]: meta["kinds"][f_inv]
        for b in blocks
        for f_inv in [next(k for k in meta["kinds"] if f(k) == b["id"])]
    }
    labels = {
        b["id"]: meta["labels"].get(next(k for k in meta["labels"] if f(k) == b["id"]), b["label"])
        for b in blocks
    }
    # joins whose inputs all come from one net
    owner = {p["id"]: p["owner_block_id"] for p in ports}
    by_target = defaultdict(list)
    for n in nets:
        for t in n["targets"]:
            by_target[t].append(n)
    drop_b, drop_n, drop_p = set(), set(), set()
    for b in blocks:
        if kinds.get(b["id"]) != "split" or not b["id"].startswith("b.join."):
            continue
        ins = [
            p["id"] for p in ports if p["owner_block_id"] == b["id"] and p["direction"] == "input"
        ]
        feeders = {n["id"]: n for pid in ins for n in by_target.get(pid, [])}
        if len(feeders) != 1:
            continue
        (fn,) = feeders.values()
        out_net = next((n for n in nets if owner.get(n["source"]) == b["id"]), None)
        if out_net is None:
            continue
        if fn["width"] == out_net["width"]:  # pure fan-in of one source: bypass
            fn["targets"] = sorted((set(fn["targets"]) - set(ins)) | set(out_net["targets"]))
            drop_b.add(b["id"])
            drop_n.add(out_net["id"])
        else:  # concat of N copies: one input, label it
            keep = sorted(ins)[0]
            fn["targets"] = sorted((set(fn["targets"]) - set(ins)) | {keep})
            drop_p |= set(ins) - {keep}
            labels[b["id"]] = f"×{len(ins)}"
            b["label"] = labels[b["id"]]
    blocks = [b for b in blocks if b["id"] not in drop_b]
    ports = [p for p in ports if p["owner_block_id"] not in drop_b and p["id"] not in drop_p]
    nets = [n for n in nets if n["id"] not in drop_n]
    kinds = {b["id"]: kinds[b["id"]] for b in blocks}
    labels = {b["id"]: labels[b["id"]] for b in blocks}
    for r, n in count.items():
        labels[r] = f"{labels[r]} ×{n}"
    for b in blocks:
        b["label"] = labels[b["id"]]
    groups = []
    for g in meta.get("teacher_groups", []):
        inst = sorted({f(i) for i in g["instances"]})
        groups.append({**g, "instances": [i for i in inst if i in kinds]})
    lanes = {}
    for b, v in meta.get("lanes", {}).items():
        if f(b) in kinds:
            lanes.setdefault(f(b), {}).update({f(o): f(i) for o, i in v.items()})
    diagram = {**diagram, "blocks": blocks, "ports": ports, "nets": nets}
    diagram = _repair(diagram, kinds, labels)
    meta = {
        **meta,
        "kinds": kinds,
        "labels": labels,
        "teacher_groups": groups,
        "lanes": lanes,
        "paths": {b: paths[k] for k in paths for b in [f(k)] if b in kinds and k not in subs},
    }
    return diagram, stage_hints(diagram, kinds), meta


def _repair(diagram: dict, kinds: dict, labels: dict) -> dict:
    """Restore the two net invariants after folding: a port is the target of one net (else a
    join block collects the drivers), and a net's width matches its targets (else an adapter
    block, 'xN' for a concat of copies, 'fields' for a narrower read)."""
    blocks, ports, nets = diagram["blocks"], diagram["ports"], diagram["nets"]
    pw = {p["id"]: p["width"] for p in ports}
    by_target = defaultdict(list)
    for n in nets:
        for t in n["targets"]:
            by_target[t].append(n)
    for t, ns in by_target.items():
        if len(ns) < 2:
            continue
        jb = _sid(f"b.join.{t}")
        if any(b["id"] == jb for b in blocks):
            jb = _sid(f"b.join2.{t}")
        blocks.append({"id": jb, "label": "join", "kind": "split", "parent_id": None})
        kinds[jb], labels[jb] = "split", "join"
        jo = f"{jb}.out"
        ports.append(_port(jo, jb, "output", pw[t]))
        pw[jo] = pw[t]
        nets.append(
            {
                "id": _sid(f"n.{jo}"),
                "source": jo,
                "targets": [t],
                "width": pw[t],
                "class": ns[0]["class"],
            }
        )
        for j, n in enumerate(ns):
            ji = f"{jb}.in{j}"
            ports.append(_port(ji, jb, "input", n["width"]))
            pw[ji] = n["width"]
            n["targets"] = sorted((set(n["targets"]) - {t}) | {ji})
    for n in list(nets):
        bad = [t for t in n["targets"] if pw[t] != n["width"]]
        if not bad:
            continue
        n["targets"] = [t for t in n["targets"] if t not in bad]
        for t in bad:
            ab = _sid(f"b.adapt.{t}")
            wide = pw[t] > n["width"]
            blocks.append({"id": ab, "label": "", "kind": "split", "parent_id": None})
            kinds[ab] = "split"
            labels[ab] = f"×{pw[t] // n['width']}" if wide and pw[t] % n["width"] == 0 else "fields"
            blocks[-1]["label"] = labels[ab]
            ai, ao = f"{ab}.in", f"{ab}.out"
            ports.append(_port(ai, ab, "input", n["width"]))
            ports.append(_port(ao, ab, "output", pw[t]))
            pw[ai], pw[ao] = n["width"], pw[t]
            n["targets"].append(ai)
            nets.append(
                {
                    "id": _sid(f"n.{ao}"),
                    "source": ao,
                    "targets": [t],
                    "width": pw[t],
                    "class": n["class"],
                }
            )
        if not n["targets"]:
            nets.remove(n)
    for p in ports:
        if p["class"] is None:
            for n in nets:
                if p["id"] == n["source"] or p["id"] in n["targets"]:
                    p["class"] = n["class"]
                    break
    return {**diagram, "blocks": blocks, "ports": ports, "nets": nets}


def choose_view(meta: dict) -> str:
    """datapath when the top is itself a datapath (pipeline registers, or several muxes /
    arithmetic units among its blocks); otherwise system (subsystems joined by interfaces)."""
    kinds = list(meta["kinds"].values())
    if "pipeline_reg" in kinds:
        return "datapath"
    if sum(k in ("mux", "alu", "adder") for k in kinds) >= 3:
        return "datapath"
    return "system"


def _teacher_groups(run, top, inst_block) -> list[dict]:
    res = run.results_full.get(run.graph.instances[top].module)
    t = run.tables_by_module.get(run.graph.instances[top].module)
    if res is None or t is None:
        return []
    rows = {r.id: r for r in t.rows}

    def blocks_of(row):
        paths = row.members or [top + "." + row.name]
        return [inst_block[p] for p in paths if p in inst_block]

    return [
        {
            "name": g.name,
            "kind": g.kind.value,
            "instances": [
                b
                for i in g.member_ids
                if i in rows and rows[i].kind == "inst"
                for b in blocks_of(rows[i])
            ],
            "logic": _sid("b.g." + g.name),
        }
        for g in res.groups
    ]


def _interfaces(run, top, port_of) -> list[dict]:
    """Teacher interfaces of the top: named groups of boundary ports (AXI channel, stream)."""
    res = run.results_full.get(run.graph.instances[top].module)
    t = run.tables_by_module.get(run.graph.instances[top].module)
    if res is None or t is None:
        return []
    rows = {r.id: r for r in t.rows}
    tinfo = run.graph.instances[top]
    out = []
    for itf in res.interfaces:
        names = [rows[i].name for i in itf.member_ids if i in rows]
        pids = [port_of[tinfo.ports[n]] for n in names if n in tinfo.ports]
        if pids:
            out.append({"name": itf.name, "protocol": itf.protocol.value, "ports": pids})
    return out


# ------------------------------------------------------------------ stages
def stage_hints(d: dict, kind_of: dict) -> dict:
    owner = {p["id"]: p["owner_block_id"] for p in d["ports"]}
    succ = defaultdict(set)
    for n in d["nets"]:
        if n["class"] in ("clock", "reset"):
            continue
        sb = owner[n["source"]]
        for t in n["targets"]:
            tb = owner[t]
            if sb and tb and sb != tb:
                succ[sb].add(tb)
    blocks = [b["id"] for b in d["blocks"]]
    regs = {b for b in blocks if kind_of[b] == "pipeline_reg"}
    preds = defaultdict(set)
    for a, ts in succ.items():
        for t in ts:
            preds[t].add(a)

    # stage = fewest pipeline registers crossed on a path from a stage-0 source (a non-pipeline
    # register such as the PC, or a block with no drivers). Feedback paths only ever make the
    # count larger, so a shortest-path fixpoint ignores them without detecting them.
    INF = 10**9
    dist = {b: INF for b in blocks}
    for b in blocks:
        if kind_of[b] == "register" or not preds[b]:
            dist[b] = 0
    changed = True
    while changed:
        changed = False
        for b in blocks:
            vals = [dist[p] + (1 if p in regs else 0) for p in preds[b] if dist[p] < INF]
            v = min(vals, default=INF)
            if v < dist[b]:
                dist[b], changed = v, True
    # a pipeline register at distance k sits on boundary k (between stage k and k+1)
    hb = {}
    for b in blocks:
        if b in regs:
            hb[b] = {"stage_boundary": dist[b] if dist[b] < INF else 0}
        else:
            s = dist[b] if dist[b] < INF else 0
            hb[b] = {"stage_index": s}
            if kind_of[b] in CTRL_KINDS:
                hb[b]["lane"] = "control"

    def col(b):
        h = hb[b]
        return 2 * h["stage_index"] if "stage_index" in h else 2 * h["stage_boundary"] + 1

    sinks = {}
    for n in d["nets"]:
        sb = owner[n["source"]]
        for t in n["targets"]:
            tb = owner[t]
            if not (sb and tb) or sb == tb:
                continue
            if col(tb) < col(sb) or (col(tb) == col(sb) and kind_of[tb] == "register"):
                sinks[f"{n['id']}|{t}"] = {"flow_role": "feedback"}
    return {"blocks": hb, "sinks": sinks, "stage_names": {}}


def main(manifest: str, out_dir: str) -> None:
    mp = Path(manifest).resolve()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for it in json.loads(mp.read_text(encoding="utf-8")):
        d = {
            "name": it["name"],
            "files": [str(mp.parent / f) for f in it["files"]],
            "top": it["top"],
        }
        diagram, hints, meta = build(d, root=it.get("root"))
        (out / f"{d['name']}.diagram.json").write_text(
            json.dumps(diagram, indent=1), encoding="utf-8"
        )
        (out / f"{d['name']}.hints.json").write_text(json.dumps(hints, indent=1))
        (out / f"{d['name']}.meta.json").write_text(json.dumps(meta, indent=1))
        print(d["name"], len(diagram["blocks"]), "blocks", len(diagram["nets"]), "nets")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
