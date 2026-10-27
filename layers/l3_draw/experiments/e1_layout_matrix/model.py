"""Shared data model for the layout experiment.

All geometry is in grid units (1 unit = `U` px). Own placers and routers use integers;
external engines (ELK, Graphviz) may return fractions.
"""

from __future__ import annotations

import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e0_reference_inputs"))

from spec import Block, Diagram, Net, Port  # noqa: E402

U = 8  # px per grid unit
GLOBAL = {"clock", "reset"}
NON_DATA = {"control", "status", "clock", "reset"}
Hints = dict[str, dict[str, dict[str, object]]]
Pt = tuple[float, float]


def norm(s: str | None) -> str:
    return (s or "").strip().lower()


def text_units(label: str, px_per_char: float = 6.4) -> int:
    """Rough width of a label in grid units (wide CJK characters count double)."""
    line = max(label.split("\n"), key=len) if label else ""
    n = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in line)
    return int(n * px_per_char / U) + 2


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h


@dataclass
class Scene:
    """A Diagram prepared for layout: who is a node, where ports sit, which nets are wires."""

    d: Diagram
    hints: Hints
    sides: str = "we"  # "we": inputs west, outputs east; "ctl_n": non-data inputs north
    pres: str = "wires"  # "wires" | "implicit" | "stubs"
    canon: bool = False  # sort everything by ID first, so input order cannot matter

    blocks: dict[str, Block] = field(init=False)
    ports: dict[str, Port] = field(init=False)
    nets: list[Net] = field(init=False)
    children: dict[str | None, list[str]] = field(init=False)
    leaves: list[str] = field(init=False)  # blocks without children
    pins: list[str] = field(init=False)  # boundary port ids, each a small node
    wires: list[Net] = field(init=False)  # nets drawn as lines
    hidden: dict[str, str] = field(init=False)  # net id -> "stub" | "implicit"
    side: dict[str, str] = field(init=False)  # port id -> W/E/N/S
    size: dict[str, tuple[int, int]] = field(init=False)  # node id -> (w, h)
    poff: dict[str, tuple[int, int]] = field(init=False)  # port id -> offset in its node
    node_of: dict[str, str] = field(init=False)  # port id -> node id it is placed with

    def __post_init__(self) -> None:
        d = self.d
        bl, po, ne = list(d.blocks), list(d.ports), list(d.nets)
        if self.canon:
            bl.sort(key=lambda b: b.id)
            po.sort(key=lambda p: p.id)
            ne = sorted(
                (n.model_copy(update={"targets": sorted(n.targets)}) for n in ne),
                key=lambda n: n.id,
            )
        self.blocks = {b.id: b for b in bl}
        self.ports = {p.id: p for p in po}
        self.nets = ne
        self.children = {}
        for b in bl:
            self.children.setdefault(b.parent_id, []).append(b.id)
        self.leaves = [b.id for b in bl if b.id not in self.children]
        self.pins = [p.id for p in po if p.owner_block_id is None]

        self.hidden = {}
        for n in ne:
            cls = norm(n.class_)
            if self.pres == "implicit" and cls in GLOBAL:
                self.hidden[n.id] = "implicit"
            elif self.pres == "stubs" and (cls in GLOBAL or len(n.targets) >= 4):
                self.hidden[n.id] = "stub"
        self.wires = [n for n in ne if n.id not in self.hidden]
        self._sizes(po)

    def _sizes(self, po: list[Port]) -> None:
        self.side, self.size, self.poff, self.node_of = {}, {}, {}, {}
        by_owner: dict[str, list[Port]] = {}
        for p in po:
            if p.owner_block_id is not None:
                by_owner.setdefault(p.owner_block_id, []).append(p)
        for bid in self.leaves:
            b = self.blocks[bid]
            ps = by_owner.get(bid, [])
            has_data = any(norm(p.class_) not in NON_DATA for p in ps)
            groups: dict[str, list[Port]] = {"W": [], "E": [], "N": [], "S": []}
            for p in ps:
                if p.direction == "output":
                    s = "E"
                elif self.sides == "ctl_n" and has_data and norm(p.class_) in NON_DATA:
                    s = "N"
                else:
                    s = "W"
                groups[s].append(p)
                self.side[p.id] = s
            w = max(6, text_units(b.label), 2 * len(groups["N"]) + 2)
            h = max(4, 2 * max(len(groups["W"]), len(groups["E"])) + 2)
            self.size[bid] = (w, h)
            for s, plist in groups.items():
                for i, p in enumerate(plist):
                    at = 2 + 2 * i
                    self.poff[p.id] = {"W": (0, at), "E": (w, at), "N": (at, 0), "S": (at, h)}[s]
                    self.node_of[p.id] = bid
        for pid in self.pins:
            p = self.ports[pid]
            w = text_units(short(pid), 5.6) + 1
            self.size[pid] = (w, 2)
            self.side[pid] = "E" if p.direction == "input" else "W"
            self.poff[pid] = (w, 1) if p.direction == "input" else (0, 1)
            self.node_of[pid] = pid
        # Ports owned by a container are positioned on its box after placement.
        for bid, ps in by_owner.items():
            if bid in self.children:
                for p in ps:
                    self.side[p.id] = "W" if p.direction == "input" else "E"

    # --- helpers used by placers ---

    @property
    def nodes(self) -> list[str]:
        return [*self.pins, *self.leaves]

    def first_leaf(self, bid: str) -> str | None:
        while bid in self.children:
            bid = self.children[bid][0]
        return bid if bid in self.size else None

    def place_node(self, pid: str) -> str | None:
        """Node used for placement purposes for a port (container ports -> first leaf)."""
        if pid in self.node_of:
            return self.node_of[pid]
        owner = self.ports[pid].owner_block_id
        return self.first_leaf(owner) if owner else None

    def chain(self, bid: str) -> list[str]:
        """Ancestors of a block, outermost first."""
        out: list[str] = []
        cur = self.blocks[bid].parent_id if bid in self.blocks else None
        while cur is not None:
            out.append(cur)
            cur = self.blocks[cur].parent_id
        return out[::-1]

    def hint(self, bid: str) -> dict[str, object]:
        """Hints for a block; IDs of `x2` copies ('ch0.b.s1') fall back to the original."""
        hb = self.hints.get("blocks", {})
        if bid in hb:
            return hb[bid]
        return hb.get(bid.split(".", 1)[1], {}) if bid.startswith("ch") else {}

    def is_feedback(self, net_id: str, target: str) -> bool:
        hs = self.hints.get("sinks", {})
        for key in (f"{net_id}|{target}", f"{strip_ch(net_id)}|{strip_ch(target)}"):
            if hs.get(key, {}).get("flow_role") == "feedback":
                return True
        return False


def strip_ch(i: str) -> str:
    return i.split(".", 1)[1] if i.startswith("ch") and "." in i else i


def short(i: str) -> str:
    """Display name for an ID: last path segment."""
    return i.rsplit(".", 1)[-1]


@dataclass
class Layout:
    """Result of placement and routing."""

    pos: dict[str, tuple[float, float]] = field(default_factory=dict)  # node id -> top-left
    boxes: dict[str, Rect] = field(default_factory=dict)  # container id -> rect
    port_xy: dict[str, Pt] = field(default_factory=dict)  # every port id -> absolute point
    wires: dict[tuple[str, str], list[Pt]] = field(default_factory=dict)  # (net, target)
    unrouted: int = 0
    notes: list[str] = field(default_factory=list)

    def rect(self, sc: Scene, nid: str) -> Rect:
        x, y = self.pos[nid]
        w, h = sc.size[nid]
        return Rect(x, y, w, h)


def finish_placement(sc: Scene, lay: Layout, pad: int = 2, top: int = 3) -> None:
    """Derive container boxes and absolute port positions from node positions."""

    def box(bid: str) -> Rect | None:
        rs = []
        for c in sc.children.get(bid, []):
            if c in sc.children:
                r = box(c)
            else:
                r = lay.rect(sc, c) if c in lay.pos else None
            if r:
                rs.append(r)
        if not rs:
            return None
        x, y = min(r.x for r in rs) - pad, min(r.y for r in rs) - top
        r = Rect(x, y, max(r.x2 for r in rs) + pad - x, max(r.y2 for r in rs) + pad - y)
        lay.boxes[bid] = r
        return r

    if not lay.boxes:
        for bid in sc.children.get(None, []):
            if bid in sc.children:
                box(bid)
    for pid, (dx, dy) in sc.poff.items():
        n = sc.node_of[pid]
        if n in lay.pos:
            lay.port_xy[pid] = (lay.pos[n][0] + dx, lay.pos[n][1] + dy)
    slot: dict[tuple[str, str], int] = {}
    for pid, p in sc.ports.items():
        r = lay.boxes.get(p.owner_block_id or "")
        if pid not in lay.port_xy and r is not None:
            s = sc.side[pid]
            i = slot[(p.owner_block_id, s)] = slot.get((p.owner_block_id, s), -1) + 1
            lay.port_xy[pid] = (r.x if s == "W" else r.x2, r.y + top + 1 + 2 * i)


def escape(sc: Scene, lay: Layout, pid: str, dist: float = 1) -> Pt:
    """Point `dist` units outside the node, straight out of the port."""
    x, y = lay.port_xy[pid]
    dx, dy = {"W": (-1, 0), "E": (1, 0), "N": (0, -1), "S": (0, 1)}[sc.side[pid]]
    return (x + dx * dist, y + dy * dist)
