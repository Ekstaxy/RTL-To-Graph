"""Per-module entity tables with stable IDs (SPEC §3).

IDs depend only on declaration order, so renaming signals or reordering
always-blocks keeps every ID unchanged (labels transfer across augmentations).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ..schema import EntityRow, EntityTableModel
from .graph import DesignGraph, EdgeType, Node

_GEN_IDX = re.compile(r"\[\d+\]")

NAME_HINTS = {
    "valid": r"valid|vld|(^|_)v(_|$)",
    "ready": r"ready|rdy",
    "req": r"(^|_)req",
    "ack": r"ack",
    "grant": r"gnt|grant",
    "state": r"state|(^|_)st(_|$)|fsm",
    "cnt": r"cnt|count|ctr|timer",
    "ptr": r"ptr|pointer|(^|_)(wp|rp|waddr|raddr)(_|$)",
    "en": r"(^|_)(en|enable|we|wen|re|ren|ld|load)(_|$)",
    "sel": r"sel|mux",
    "data": r"data|(^|_)(din|dout|wdata|rdata|payload)(_|$)",
    "addr": r"addr|adr",
    "stall": r"stall|hold|wait",
    "flush": r"flush|kill",
    "full": r"full",
    "empty": r"empty",
    "busy": r"busy|pending|active",
    "done": r"done|finish|complete",
    "err": r"err|fault|exc",
    "irq": r"irq|intr|interrupt",
}
_HINT_RE = {k: re.compile(v, re.I) for k, v in NAME_HINTS.items()}


def name_hints(name: str) -> list[str]:
    return [k for k, r in _HINT_RE.items() if r.search(name)]


@dataclass
class EntityTable:
    design: str
    module: str
    canonical_instance: str
    file: str
    line_start: int
    line_end: int
    rows: list[EntityRow]
    key_to_id: dict[str, str] = field(
        default_factory=dict
    )  # graph node key / instance path -> entity id
    children: dict[str, str] = field(default_factory=dict)  # I-id -> child definition name

    def by_id(self) -> dict[str, EntityRow]:
        return {r.id: r for r in self.rows}

    def by_name(self) -> dict[str, EntityRow]:
        return {r.name: r for r in self.rows}

    def model(self) -> EntityTableModel:
        return EntityTableModel(
            design=self.design,
            module=self.module,
            canonical_instance=self.canonical_instance,
            file=self.file,
            line_start=self.line_start,
            line_end=self.line_end,
            rows=self.rows,
        )

    def source_text(self, numbered: bool = True) -> str:
        try:
            lines = Path(self.file).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        seg = lines[self.line_start - 1 : self.line_end]
        if not numbered:
            return "\n".join(seg)
        return "\n".join(f"{i:4d}| {ln}" for i, ln in enumerate(seg, start=self.line_start))


def _entity_kind(n: Node) -> str:
    if n.port_dir == "in":
        return "port_in"
    if n.port_dir == "out":
        return "port_out"
    if n.port_dir == "inout":
        return "port_inout"
    if n.depth is not None:
        return "mem"
    if n.is_latch:
        return "latch"
    if n.is_state:
        return "reg"
    if n.local:
        return "local"
    if n.driven_by & {"always_comb", "always"}:
        return "comb"
    return "wire"


def _is_noise(n: Node) -> bool:
    if n.loop_var:
        return True
    t = n.type_str.strip()
    return t in ("integer", "int", "genvar") and len(n.name) <= 2


def _module_span(G: DesignGraph, inst_path: str) -> tuple[str, int, int]:
    """File + line range of the module definition of a canonical instance."""
    design = G.design
    design.compilation.getRoot()
    # locate the InstanceSymbol by path (walk from tops)
    target = None
    for top in design.tops:
        stack = [top]
        while stack:
            s = stack.pop()
            if s.hierarchicalPath == inst_path:
                target = s
                break
            stack.extend(_child_insts(s.body))
        if target:
            break
    if target is None:
        return "", 0, 0
    defn = target.definition
    sm = design.sm
    try:
        rng = defn.syntax.sourceRange
        f = design.original(str(Path(str(sm.getFullPath(rng.start.buffer)))))
        return f, int(sm.getLineNumber(rng.start)), int(sm.getLineNumber(rng.end))
    except Exception:
        return design.file_of(defn), design.line_of(defn), design.line_of(defn)


def _child_insts(scope):
    from pyslang import ast

    out = []
    for m in scope:
        if isinstance(m, ast.InstanceSymbol):
            out.append(m)
        elif isinstance(m, ast.InstanceArraySymbol):
            out.extend(_child_insts(m.elements) if hasattr(m, "elements") else [])
        elif isinstance(m, ast.GenerateBlockSymbol) and not m.isUninstantiated:
            out.extend(_child_insts(m))
        elif isinstance(m, ast.GenerateBlockArraySymbol):
            for e in m.entries:
                if not e.isUninstantiated:
                    out.extend(_child_insts(e))
    return out


def canonical_instances(G: DesignGraph) -> list[tuple[str, str]]:
    """(module, canonical instance path) in bottom-up (post-order) order, one per definition."""
    seen: dict[str, str] = {}
    order: list[tuple[str, str]] = []

    def visit(path: str):
        info = G.instances[path]
        for c in info.children:
            visit(c)
        if info.module not in seen:
            seen[info.module] = path
            order.append((info.module, path))

    for t in G.tops:
        visit(t)
    return order


def clock_reset_nets(G: DesignGraph) -> tuple[set[str], set[str]]:
    """Nodes that act as clock / reset anywhere, propagated across PORT edges."""
    clk = {s for s, _, d in G.g.edges(data=True) if d["type"] == EdgeType.CLOCK}
    rst = {s for s, _, d in G.g.edges(data=True) if d["type"] == EdgeType.RESET}

    def wire_preds(k: str) -> list[str]:
        """PORT sources of k when the connection is a single net (`.rst(rst)`), else []:
        `.i_reset(i_reset || !i_valid)` must not turn i_valid into a reset."""
        ps = [p for p, _et in G.preds(k, {EdgeType.PORT})]
        return ps if len(ps) == 1 else []

    def spread(seed: set[str]) -> set[str]:
        out, stack = set(seed), list(seed)
        while stack:
            k = stack.pop()
            nbs = wire_preds(k) + [t for t, _et in G.succs(k, {EdgeType.PORT}) if wire_preds(t)]
            for nb in nbs:
                if nb not in out:
                    out.add(nb)
                    stack.append(nb)
        return out

    return spread(clk), spread(rst)


def build_entity_table(G: DesignGraph, module: str, inst_path: str, _cr=None) -> EntityTable:
    info = G.instances[inst_path]
    clk_nets, rst_nets = _cr if _cr is not None else clock_reset_nets(G)
    nodes = [n for n in G.nodes.values() if n.inst == inst_path and not _is_noise(n)]

    # ---- collapse generate copies: g[0].r, g[1].r -> g[*].r
    groups: dict[str, list[Node]] = defaultdict(list)
    for n in nodes:
        groups[_GEN_IDX.sub("[*]", n.rel)].append(n)

    # ---- child instances, collapsed the same way (u[0], u[1] -> u[*])
    child_groups: dict[str, list[str]] = defaultdict(list)
    for c in info.children:
        rel = c[len(inst_path) + 1 :]
        child_groups[_GEN_IDX.sub("[*]", rel)].append(c)

    # ---- order by declaration position (line, char offset): invariant under renaming
    sig_items = sorted(groups.items(), key=lambda kv: min((n.line, n.offset) for n in kv[1]))
    inst_items = sorted(child_groups.items(), key=lambda kv: (G.instances[kv[1][0]].line, kv[0]))

    key_to_id: dict[str, str] = {}
    rows: list[EntityRow] = []
    for i, (_name, ns) in enumerate(sig_items, start=1):
        eid = f"E{i}"
        for n in ns:
            key_to_id[n.key] = eid
    children: dict[str, str] = {}
    for i, (_name, paths) in enumerate(inst_items, start=1):
        iid = f"I{i}"
        children[iid] = G.instances[paths[0]].module
        for p in paths:
            key_to_id[p] = iid
            # route the child's port nodes to the instance entity
            for pk in G.instances[p].ports.values():
                key_to_id.setdefault(pk, iid)

    def eid_of(key: str) -> str | None:
        return key_to_id.get(key)

    # ---- per-entity features
    for name, ns in sig_items:
        eid = key_to_id[ns[0].key]
        n0 = ns[0]
        fin, fout, cfo, afo = set(), set(), set(), set()
        clock = reset = False
        for n in ns:
            for s, _t in G.preds(n.key):
                o = eid_of(s)
                if o and o != eid:
                    fin.add(o)
            for t, et in G.succs(n.key):
                o = eid_of(t)
                if et == EdgeType.CLOCK:
                    clock = True
                if et == EdgeType.RESET:
                    reset = True
                if o and o != eid:
                    fout.add(o)
                    if et == EdgeType.CONTROL:
                        cfo.add(o)
                    if et == EdgeType.ADDR:
                        afo.add(o)
        if any(n.key in clk_nets for n in ns):
            clock = True
        elif any(n.key in rst_nets for n in ns):
            reset = True
        auto = "CLOCK" if clock else ("RESET" if reset else None)
        driven = sorted(set().union(*(n.driven_by for n in ns)))
        rows.append(
            EntityRow(
                id=eid,
                name=name,
                kind=_entity_kind(n0),
                width=n0.width,
                depth=n0.depth,
                type_str=n0.type_str,
                enum_values=n0.enum_values,
                driven_by=driven,
                fanin=len(fin),
                fanout=len(fout),
                ctrl_fanout=len(cfo),
                addr_fanout=len(afo),
                is_state=any(n.is_state for n in ns),
                fsm_candidate=False,
                auto_role=auto,
                name_hints=name_hints(name),
                line=n0.line,
                members=[n.key for n in ns] if len(ns) > 1 else [],
            )
        )

    for iid, (name, paths) in zip(
        sorted(children, key=lambda x: int(x[1:])), inst_items, strict=False
    ):
        ci = G.instances[paths[0]]
        fin, fout = set(), set()
        for p in paths:
            for pk in G.instances[p].ports.values():
                for s, et in G.preds(pk):
                    o = eid_of(s)
                    if o and o != iid and et != EdgeType.CLOCK:
                        fin.add(o)
                for t, _et in G.succs(pk):
                    o = eid_of(t)
                    if o and o != iid:
                        fout.add(o)
        rows.append(
            EntityRow(
                id=iid,
                name=name,
                kind="inst",
                definition=ci.module,
                line=ci.line,
                fanin=len(fin),
                fanout=len(fout),
                members=paths if len(paths) > 1 else [],
            )
        )

    _mark_fsm(G, rows, key_to_id, sig_items)
    f, l0, l1 = _module_span(G, inst_path)
    return EntityTable(
        design=G.design.name,
        module=module,
        canonical_instance=inst_path,
        file=f,
        line_start=l0,
        line_end=l1,
        rows=rows,
        key_to_id=key_to_id,
        children=children,
    )


def _mark_fsm(G: DesignGraph, rows: list[EntityRow], key_to_id, sig_items) -> None:
    """SPEC §3.1 FSM-candidate rule."""
    row_by_id = {r.id: r for r in rows}
    for _name, ns in sig_items:
        n = ns[0]
        if not n.is_state or n.width == 0 or n.width > 8 or n.depth is not None:
            continue
        k = n.key
        self_ctrl = False
        consts = n.const_assigns
        counter_like = k in n.arith_srcs
        via_next = False  # explicit next-state variable (classic FSM coding style)
        # direct self control dependency
        for s, _et in G.preds(k, {EdgeType.CONTROL}):
            if s == k:
                self_ctrl = True
        # through a combinational next-state variable
        for s, _et in G.preds(k, {EdgeType.DATA}):
            sn = G.nodes.get(s)
            if sn is None or sn.is_state or s == k:
                continue
            if any(p == k for p, _ in G.preds(s, {EdgeType.CONTROL})):
                self_ctrl = True
                via_next = True
                consts += sn.const_assigns
            if k in sn.arith_srcs:
                counter_like = True
        if counter_like and not n.enum_values:
            continue
        if not n.enum_values and not n.case_selector:
            # an FSM state is decoded as a whole value (case / == const); bit-tested valid pipes
            # are not
            continue
        if n.width == 1 and not n.enum_values and not via_next:
            # a 1-bit flag updated in place (busy/locked) is a flag, not an FSM
            # x <= x + 1 style: a counter, not a state machine
            continue
        if bool(n.enum_values) or (self_ctrl and consts >= 3):
            if bool(n.enum_values) and not self_ctrl and consts < 2:
                continue
            row_by_id[key_to_id[k]].fsm_candidate = True


def build_entity_tables(G: DesignGraph) -> list[EntityTable]:
    cr = clock_reset_nets(G)
    return [build_entity_table(G, m, p, cr) for m, p in canonical_instances(G)]
