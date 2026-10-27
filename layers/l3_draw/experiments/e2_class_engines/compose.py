"""Bottom-up composition: every container is laid out by the engine its class asks for.

Pass 1 (inner to outer): each container becomes a `Level` whose items are its direct
children (leaves with their Scene size, sub-containers with the size pass 1 gave them, and
at the root the boundary pins). The level's engine fills local positions and the level
size. Pass 2 (outer to inner) turns local positions into absolute ones and writes every
container box itself, so e1's finish_placement only has to place ports.

Routing is global A* (e1 route_astar) on the finished placement: engines that are not ELK
have no router of their own, and mixing ELK's native routes with A* produced overlaps in
the X3 probe (elkx.read). The price is A*'s known weakness on tight placements; engines
here leave >= 4 units between items.

Engines (name -> function(sc, level, side)): "elk" (layered, placement only), "busbar",
"arrays", "cpsat", "grid". A class->engine map chooses per level; the sidecar's
`view_level` and `expected` are respected through classify.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import classify
from e1lib import (
    GLOBAL,
    NON_DATA,
    Layout,
    Rect,
    Scene,
    finish_placement,
    measure,
    norm,
    render,
    resize,
    roundtrip,
    route_astar,
    spec,
    text_units,
)

PAD, TOP = 2, 3  # container padding: e1's finish_placement defaults
GAP = 5  # free units between items, enough for A*'s keep-out rings and port reservations


@dataclass
class Item:
    id: str
    w: int
    h: int
    kind: str  # leaf | container | pin
    deg: int = 0


@dataclass
class Level:
    cid: str  # "" for the root
    cls: str
    engine: str
    items: list[Item]
    edges: list[tuple[str, str, str, str]]  # u item, v item, net id, net class
    hub: str | None = None
    pos: dict[str, tuple[int, int]] = field(default_factory=dict)
    size: tuple[int, int] = (0, 0)
    notes: list[str] = field(default_factory=list)

    def item(self, iid: str) -> Item:
        return next(i for i in self.items if i.id == iid)

    def origin(self) -> tuple[int, int]:
        return (0, 0) if self.cid == "" else (PAD, TOP)

    def finish(self) -> None:
        """Shift content to the level origin and set the size from the content bbox."""
        if not self.pos:
            self.size = (8, 5)
            return
        ox, oy = self.origin()
        mx = min(x for x, _y in self.pos.values())
        my = min(y for _x, y in self.pos.values())
        self.pos = {k: (int(x - mx + ox), int(y - my + oy)) for k, (x, y) in self.pos.items()}
        w = max(self.pos[i.id][0] + i.w for i in self.items if i.id in self.pos) + PAD
        h = max(self.pos[i.id][1] + i.h for i in self.items if i.id in self.pos) + PAD
        self.size = (int(w), int(h))


DEFAULT_MAP = {"A": "elk", "B": "elk", "C": "elk", "D": "busbar", "E": "arrays"}


def _engines():
    import arrays
    import busbar
    import cpsat
    import elklevel

    return {"elk": elklevel.place_level, "busbar": busbar.place_level,
            "arrays": arrays.place_level, "cpsat": cpsat.place_level,
            "grid": busbar.place_grid}


def apply_replicate(sc: Scene, side: dict) -> None:
    """'xN' in the label of replicated blocks (the figure's stacked-box count)."""
    for bid, info in side.get("nodes", {}).items():
        rep = info.get("replicate")
        if rep and bid in sc.blocks:
            b = sc.blocks[bid]
            label = f"{b.label} ×{rep['count']}"
            sc.blocks[bid] = b.model_copy(update={"label": label})
            if bid in sc.size:
                w, h = sc.size[bid]
                resize(sc, bid, max(w, text_units(label)), h)


def _item_at(parent: dict, owner: dict, cid: str, ids: set[str], pid: str) -> str | None:
    """The item of level `cid` that port `pid` belongs to (pins only at the root)."""
    o = owner.get(pid)
    if o is None:
        return pid if cid == "" and pid in ids else None
    return classify.child_at(parent, cid, o)


def build_levels(sc: Scene, side: dict, engine_map: dict[str, str],
                 rules: str = "cal") -> dict[str, Level]:
    cls = classify.classify(sc.d, side, rules)
    parent = {b.id: (b.parent_id or "") for b in sc.blocks.values()}
    owner = {p.id: p.owner_block_id for p in sc.ports.values()}
    levels: dict[str, Level] = {}
    for cid, kids in classify.levels(sc.d).items():
        c = cls[cid]["class"]
        eng = engine_map.get(cid) or engine_map.get(c) or "elk"
        items = []
        for k in kids:
            if k in sc.children:
                items.append(Item(k, 0, 0, "container"))
            else:
                w, h = sc.size[k]
                items.append(Item(k, w, h, "leaf"))
        if cid == "":
            for pid in sc.pins:
                w, h = sc.size[pid]
                items.append(Item(pid, w, h, "pin"))
        ids = {i.id for i in items}
        edges = []
        for n in sc.wires:
            u = _item_at(parent, owner, cid, ids, n.source)
            for t in n.targets:
                v = _item_at(parent, owner, cid, ids, t)
                if u and v and u != v:
                    edges.append((u, v, n.id, norm(n.class_)))
        deg: dict[str, set[str]] = {}
        for u, v, _n, c_ in edges:
            if c_ not in NON_DATA:
                deg.setdefault(u, set()).add(v)
                deg.setdefault(v, set()).add(u)
        for i in items:
            i.deg = len(deg.get(i.id, ()))
        levels[cid] = Level(cid, c, eng, items, edges, cls[cid]["ind"].get("hub"))
    return levels


def compose(sc: Scene, side: dict, engine_map: dict[str, str] | None = None,
            rules: str = "cal", cpsat_seconds: float = 30.0) -> tuple[Layout, dict[str, Level]]:
    engines = _engines()
    engine_map = {**DEFAULT_MAP, **(engine_map or {})}
    levels = build_levels(sc, side, engine_map, rules)

    def depth(cid: str) -> int:
        return 0 if cid == "" else 1 + depth(sc.blocks[cid].parent_id or "")

    # pass 1: inner to outer; the CP-SAT budget is per drawing, split over its levels
    n_cpsat = sum(1 for lv in levels.values() if lv.engine == "cpsat")
    per_level = cpsat_seconds / max(1, n_cpsat)
    for cid in sorted(levels, key=depth, reverse=True):
        lv = levels[cid]
        for it in lv.items:
            if it.kind == "container":
                it.w, it.h = levels[it.id].size
        lv.notes.append(f"{cid or 'root'}: {lv.cls} -> {lv.engine}")
        engines[lv.engine](sc, lv, side, seconds=per_level)
        lv.finish()
    # pass 2: outer to inner
    lay = Layout()

    def place(cid: str, X: int, Y: int) -> None:
        lv = levels[cid]
        for it in lv.items:
            x, y = lv.pos[it.id]
            ax, ay = X + x, Y + y
            if it.kind == "container":
                lay.boxes[it.id] = Rect(ax, ay, it.w, it.h)
                place(it.id, ax, ay)
            else:
                lay.pos[it.id] = (ax, ay)

    place("", 0, 0)
    for cid in sc.children:  # empty containers still need a box for the round trip
        if cid is not None and cid not in lay.boxes:
            lay.boxes[cid] = Rect(0, 0, 8, 5)
    finish_placement(sc, lay)
    route_astar(sc, lay, order="class")
    for lv in levels.values():
        lay.notes += lv.notes
    return lay, levels


def stack_shadows(svg: str, sc: Scene, side: dict) -> str:
    """Two offset copies behind every replicated block: the figures' 'xN' stack."""
    for bid, info in side.get("nodes", {}).items():
        if not info.get("replicate") or bid not in sc.blocks:
            continue
        m = re.search(rf'<g data-rtl2d-kind="block" data-rtl2d-id="{re.escape(bid)}">'
                      r'(?:<rect|<polygon)[^>]*?', svg)
        if not m:
            continue
        r = re.search(r'x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"',
                      svg[m.start():m.end() + 120])
        if not r:
            continue
        x, y, w, h = map(float, r.groups())
        shadow = "".join(
            f'<rect x="{x + d:.1f}" y="{y - d:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="white" stroke="#555" stroke-width="1"/>' for d in (8, 4))
        svg = svg[:m.start()] + shadow + svg[m.start():]
    return svg


def draw(d: spec.Diagram, hints: dict, side: dict, engine_map: dict[str, str] | None = None,
         pres: str = "implicit", canon: bool = True, title: str = "", rules: str = "cal",
         cpsat_seconds: float = 30.0):
    issues = spec.validate(d)
    if issues:
        raise ValueError("refused: " + "; ".join(issues[:3]))
    sc = Scene(d, hints, sides="we", pres=pres, canon=canon)
    apply_replicate(sc, side)
    lay, levels = compose(sc, side, engine_map, rules, cpsat_seconds)
    svg = stack_shadows(render(sc, lay, title), sc, side)
    m = measure(sc, lay)
    m["hidden_nets"] = len(sc.hidden)
    m["levels"] = {cid: (lv.cls, lv.engine) for cid, lv in levels.items()}
    return svg, m, roundtrip(sc, svg), lay, sc


__all__ = ["GLOBAL", "Item", "Level", "compose", "draw", "GAP", "PAD", "TOP"]
