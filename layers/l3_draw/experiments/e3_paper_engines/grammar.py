"""From a Diagram to the *paper-figure graph* (memo §2.1), before any layout.

What papers do, and what this module does:
1. clock and reset are not drawn;
2. one arrow per pair of blocks: every net between two leaves becomes one edge, and the
   two directions merge into one double-headed arrow (a read/write interface);
3. boundary ports with the same base name (gpio_i / gpio_o) are one terminal;
4. bus / crossbar / NoC blocks (sidecar `role`, or kind bus) are bars;
5. replicated blocks carry "xN" and are drawn as a stack;
6. containers are titled; top-level containers get a subsystem colour.

Every (net, sink) of the Diagram that crosses between two different drawn items stays
recorded in the edge that represents it (`members`), so the drawing can be checked
against the Diagram (check.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from p3lib import spec

GLOBAL = {"clock", "reset"}
CHAR_W = 6.6  # px per character at 12 px bold
NODE_H = 40
BAR_H = 24


@dataclass
class PNode:
    id: str
    label: str
    kind: str  # leaf | bar | pin | container
    cat: str = "unit"  # colour category of a leaf
    parent: str = ""  # "" = root
    w: float = 0
    h: float = 0
    count: int = 1
    deg: int = 0
    side: str = ""  # pins: "in" | "out" | "io"
    ports: list[str] = field(default_factory=list)  # diagram port ids (pins)


@dataclass
class PEdge:
    id: str
    a: str
    b: str
    cls: str  # bus | data | control
    bidir: bool
    width: int
    members: list[tuple[str, str]] = field(default_factory=list)  # (net, sink port)
    label: str = ""


@dataclass
class PGraph:
    name: str
    nodes: dict[str, PNode]
    edges: list[PEdge]
    children: dict[str, list[str]]  # container id ("" root) -> child node ids
    side: dict
    colour_of: dict[str, int] = field(default_factory=dict)  # top container -> palette ix

    def leaves(self) -> list[PNode]:
        return [n for n in self.nodes.values() if n.kind != "container"]

    def containers(self) -> list[PNode]:
        return [n for n in self.nodes.values() if n.kind == "container"]

    def top_of(self, nid: str) -> str:
        cur = nid
        while self.nodes[cur].parent:
            cur = self.nodes[cur].parent
        return cur

    def chain(self, nid: str) -> list[str]:
        out = []
        cur = self.nodes[nid].parent
        while cur:
            out.append(cur)
            cur = self.nodes[cur].parent
        return out[::-1]


CATS = [
    ("memory", ("memory", "regfile", "fifo", "sram", "cache", "buffer", "rom", "flash", "otp",
                "queue", "mem")),
    ("control", ("controller", "ctrl", "scheduler", "manager", "mgr", "decoder", "fsm")),
    ("cpu", ("cpu", "core", "tile", "ibex", "risc")),
    ("io", ("peripheral", "uart", "gpio", "spi", "i2c", "usb", "jtag", "pwm", "timer", "pad",
            "pin", "if", "interface", "analog", "dma")),
    ("compute", ("comb", "adder", "mac", "alu", "mux", "gate", "unit", "engine", "datapath",
                 "processing", "aes", "hmac", "kmac", "otbn")),
]


def category(kind: str, label: str) -> str:
    k, lab = (kind or "").lower(), (label or "").lower()
    for cat, keys in CATS:
        if k in keys:
            return cat
    for cat, keys in CATS:
        if any(re.search(rf"\b{x}", lab) for x in keys):
            return cat
    return "compute"


def wrap(label: str, width: int = 22) -> list[str]:
    words, lines, cur = label.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def size_of(n: PNode) -> tuple[float, float]:
    if n.kind == "pin":
        return (max(48, len(n.label) * 6.2 + 16), 20)
    if n.kind == "bar":  # one line of text, the bar is as long as it needs
        return (max(160, len(n.label) * CHAR_W + 60, 34 * n.deg), BAR_H)
    lines = wrap(n.label)
    w = max(len(s) for s in lines) * CHAR_W + 28
    h = max(NODE_H, 16 * len(lines) + 20)
    return (max(84, w), h)


def _base(pid: str) -> str:
    name = pid.rsplit(".", 1)[-1]
    return re.sub(r"(_i|_o|_in|_out|_rx|_tx)$", "", name)


def build(name: str, d: spec.Diagram, side: dict) -> PGraph:
    nodes_side = side.get("nodes", {})
    parent = {b.id: b.parent_id or "" for b in d.blocks}
    is_cont = {b.parent_id for b in d.blocks if b.parent_id}
    nodes: dict[str, PNode] = {}
    for b in d.blocks:
        info = nodes_side.get(b.id, {})
        cnt = info.get("replicate", {}).get("count", 1)
        label = b.label + (f" ×{cnt}" if cnt > 1 else "")
        if b.id in is_cont:
            nodes[b.id] = PNode(b.id, label, "container", parent=parent[b.id], count=cnt)
            continue
        bar = info.get("role") in ("bus", "crossbar", "noc") or (b.kind or "").lower() == "bus"
        nodes[b.id] = PNode(b.id, label, "bar" if bar else "leaf",
                            category(b.kind or "", b.label), parent[b.id], count=cnt)
    owner = {p.id: p.owner_block_id for p in d.ports}
    pin_of: dict[str, str] = {}
    groups = side.get("pin_groups", {})  # port id -> interface name (ADR-0003 interfaces)
    for p in d.ports:
        if p.owner_block_id is None and (p.class_ or "").lower() not in GLOBAL:
            base = groups.get(p.id) or _base(p.id)
            pid = f"pin.{base}"
            if pid not in nodes:
                nodes[pid] = PNode(pid, base, "pin", "io", "")
            nodes[pid].ports.append(p.id)
            pin_of[p.id] = pid
    for n in nodes.values():
        if n.kind == "pin":
            dirs = {next(p for p in d.ports if p.id == q).direction for q in n.ports}
            n.side = "io" if len(dirs) == 2 else ("in" if "input" in dirs else "out")

    def item(pid: str) -> str | None:
        o = owner.get(pid)
        if o is None:
            return pin_of.get(pid)
        return o

    pairs: dict[tuple[str, str], PEdge] = {}
    for net in d.nets:
        c = (net.class_ or "data").lower()
        if c in GLOBAL:
            continue
        u = item(net.source)
        for t in net.targets:
            v = item(t)
            if not u or not v or u == v:
                continue
            key = tuple(sorted((u, v)))
            e = pairs.get(key)
            if e is None:
                e = pairs[key] = PEdge(f"e{len(pairs)}", u, v, "control", False, 0)
            if (u, v) != (e.a, e.b):
                e.bidir = True
            rank = {"control": 0, "status": 0, "data": 1, "bus": 2}
            cc = c if c in rank else "data"
            if rank[cc] > rank[e.cls if e.cls in rank else "control"]:
                e.cls = cc
            if (net.id, t) not in e.members:
                e.members.append((net.id, t))
                if t not in [m[1] for m in e.members[:-1]]:
                    e.width += net.width
    edges = list(pairs.values())
    for e in edges:
        nets = {m[0] for m in e.members}
        if len(nets) == 1:
            e.label = next(iter(nets)).split(".", 1)[-1]
    deg: dict[str, set[str]] = {}
    for e in edges:
        deg.setdefault(e.a, set()).add(e.b)
        deg.setdefault(e.b, set()).add(e.a)
    for n in nodes.values():
        n.deg = len(deg.get(n.id, ()))
        if n.kind != "container":
            n.w, n.h = size_of(n)
    children: dict[str, list[str]] = {"": []}
    for n in nodes.values():
        children.setdefault(n.parent, []).append(n.id)
        if n.kind == "container":
            children.setdefault(n.id, [])
    for k in children:
        children[k].sort()
    tops = sorted(c for c in children[""] if nodes[c].kind == "container")
    g = PGraph(name, nodes, edges, children, side, {t: i for i, t in enumerate(tops)})
    return g


def check(g: PGraph, d: spec.Diagram) -> list[str]:
    """Every (net, sink) between two different items is represented by exactly one edge."""
    owner = {p.id: p.owner_block_id for p in d.ports}
    pin_of = {q: n.id for n in g.nodes.values() if n.kind == "pin" for q in n.ports}
    have = {(m[0], m[1]) for e in g.edges for m in e.members}
    issues = []
    for net in d.nets:
        if (net.class_ or "").lower() in GLOBAL:
            continue
        u = owner.get(net.source) or pin_of.get(net.source)
        for t in net.targets:
            v = owner.get(t) or pin_of.get(t)
            if u and v and u != v and (net.id, t) not in have:
                issues.append(f"{net.id} -> {t} not represented")
    return issues
