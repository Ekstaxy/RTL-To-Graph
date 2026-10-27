"""Placement engines for the paper-figure graph. All coordinates are px, top-left.

Engines with their own hierarchy handling get the whole graph:
  elk      ELK layered, INCLUDE_CHILDREN (reference: the e1/e2 baseline family)
  cola     WebCoLa (Dwyer): stress majorisation with non-overlap and nested group
           constraints, the constraint-based layout the memo lists for C-class figures
  dot      Graphviz dot with clusters (layered, Sugiyama)
  fdp      Graphviz fdp with clusters (force-directed)
  osage    Graphviz osage: packs clusters into an array (closest to a figure's grid)
Engines placed one container level at a time, bottom-up (`compose`):
  hola     HOLA (Kieffer et al. 2015) through libdialect: human-like orthogonal layout,
           tuned on what people do by hand (compact, grid-like, symmetric)
  busbar   e2's bus-bar grammar: bars across the level, attached units in rows
  grid     rows of equal cells in BFS order wrapped to 16:9 (D2 grid / rectpacking idea)
  cpsat    OR-Tools CP-SAT on a cell grid (Yoghourdjian et al. 2015), with a reward for
           sharing a row or column with a neighbour
Routing is separate (route.py, libavoid) and the same for every engine.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field

import p3lib
from grammar import PGraph, PNode

PAD, TITLE, GAP = 16, 30, 36


@dataclass
class Place:
    pos: dict[str, tuple[float, float]] = field(default_factory=dict)  # top-left
    boxes: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ helpers
def level_edges(g: PGraph, cid: str) -> list[tuple[str, str, float]]:
    """Edges between direct children of `cid` (weighted by member count)."""
    kids = set(g.children.get(cid, []))

    def at(nid: str) -> str | None:
        cur = nid
        while cur and cur not in kids:
            cur = g.nodes[cur].parent
        return cur if cur in kids else None

    w: dict[tuple[str, str], float] = {}
    for e in g.edges:
        a, b = at(e.a), at(e.b)
        if cid and (a is None or b is None):
            continue
        if cid == "" and (a is None or b is None):
            continue
        if a and b and a != b:
            k = (a, b)
            w[k] = w.get(k, 0) + 1 + (1 if e.cls == "bus" else 0)
    return [(a, b, x) for (a, b), x in w.items()]


def fit_boxes(g: PGraph, pl: Place) -> None:
    """Container boxes from their content (inner first)."""
    def depth(c: str) -> int:
        return len(g.chain(c))
    for c in sorted((n.id for n in g.containers()), key=depth, reverse=True):
        rs = []
        for k in g.children.get(c, []):
            if k in pl.boxes:
                rs.append(pl.boxes[k])
            elif k in pl.pos:
                x, y = pl.pos[k]
                rs.append((x, y, g.nodes[k].w, g.nodes[k].h))
        if not rs:
            continue
        x0 = min(r[0] for r in rs) - PAD
        y0 = min(r[1] for r in rs) - TITLE
        x1 = max(r[0] + r[2] for r in rs) + PAD
        y1 = max(r[1] + r[3] for r in rs) + PAD
        pl.boxes[c] = (x0, y0, x1 - x0, y1 - y0)


def pins_to_border(g: PGraph, pl: Place) -> None:
    """Terminals on the chip border: inputs left, outputs right, at the height of what they
    connect to (presentation rule, the same for every engine)."""
    pins = [n for n in g.nodes.values() if n.kind == "pin"]
    if not pins:
        return
    rest = [(pl.pos[k], g.nodes[k]) for k in pl.pos if g.nodes[k].kind != "pin"]
    xs = [p[0] for p, _n in rest] + [b[0] for b in pl.boxes.values()]
    xe = [p[0] + n.w for p, n in rest] + [b[0] + b[2] for b in pl.boxes.values()]
    if not xs:
        return
    left, right = min(xs) - 90, max(xe) + 50
    other = {}
    for e in g.edges:
        for p, q in ((e.a, e.b), (e.b, e.a)):
            if g.nodes[p].kind == "pin" and q in pl.pos:
                other.setdefault(p, []).append(pl.pos[q][1] + g.nodes[q].h / 2)
    cols: dict[str, list[tuple[float, PNode]]] = {"L": [], "R": []}
    for n in pins:
        y = sum(other.get(n.id, [0])) / max(1, len(other.get(n.id, [0])))
        col = "R" if n.side == "out" else "L"
        if n.side == "io" and n.id in pl.pos:
            col = "R" if pl.pos[n.id][0] > (left + right) / 2 else "L"
        cols[col].append((y, n))
    for col, lst in cols.items():
        lst.sort(key=lambda t: t[0])
        last = -1e9
        for y, n in lst:
            y = max(y - n.h / 2, last + n.h + 10)
            last = y
            pl.pos[n.id] = (left - n.w + 60 if col == "L" else right, y)


# ------------------------------------------------------------------ ELK
def place_elk(g: PGraph) -> Place:
    import elkx  # e2's ELK runner

    def node(nid: str) -> dict:
        n = g.nodes[nid]
        if n.kind == "container":
            return {"id": nid, "children": [node(c) for c in g.children.get(nid, [])],
                    "layoutOptions": {"elk.padding":
                                      f"[top={TITLE},left={PAD},bottom={PAD},right={PAD}]"}}
        lo = {}
        if n.kind == "pin":
            lo["elk.layered.layering.layerConstraint"] = "LAST" if n.side == "out" else "FIRST"
        return {"id": nid, "width": n.w, "height": n.h, "layoutOptions": lo}

    graph = {"id": "root",
             "layoutOptions": {**elkx.LAYERED, "elk.hierarchyHandling": "INCLUDE_CHILDREN",
                               "elk.spacing.nodeNode": 30,
                               "elk.layered.spacing.nodeNodeBetweenLayers": 50},
             "children": [node(c) for c in g.children[""]],
             "edges": [{"id": e.id, "sources": [e.a], "targets": [e.b]} for e in g.edges]}
    out = elkx.run(graph)
    pl = Place()

    def walk(n: dict, ox: float, oy: float) -> None:
        for c in n.get("children", []):
            x, y = ox + c["x"], oy + c["y"]
            if g.nodes[c["id"]].kind == "container":
                pl.boxes[c["id"]] = (x, y, c["width"], c["height"])
                walk(c, x, y)
            else:
                pl.pos[c["id"]] = (x, y)
    walk(out, 0, 0)
    pins_to_border(g, pl)
    return pl


# ------------------------------------------------------------------ WebCoLa
COLA_SCRIPT = r"""
const cola = require(process.argv[1]);
let buf = ""; process.stdin.on("data", c => buf += c);
process.stdin.on("end", () => {
  const G = JSON.parse(buf);
  const L = new cola.Layout().size([G.W, G.H]).nodes(G.nodes).links(G.links)
    .groups(G.groups).avoidOverlaps(true).handleDisconnected(true)
    .linkDistance(l => l.d).convergenceThreshold(1e-4);
  if (G.flow) L.flowLayout("x", G.flow);
  L.start(40, 40, 80, 0, false);
  process.stdout.write(JSON.stringify({
    nodes: G.nodes.map(n => [n.x - n.width / 2, n.y - n.height / 2]),
    groups: G.groups.map(g => g.bounds ? [g.bounds.x, g.bounds.y, g.bounds.X - g.bounds.x,
                                          g.bounds.Y - g.bounds.y] : null)}));
});
"""


def place_cola(g: PGraph, flow: float = 0) -> Place:
    leaves = [n for n in g.nodes.values() if n.kind != "container"]
    ix = {n.id: i for i, n in enumerate(leaves)}
    conts = g.containers()
    gx = {c.id: i for i, c in enumerate(conts)}
    groups = []
    for c in conts:
        kids = g.children.get(c.id, [])
        groups.append({"leaves": [ix[k] for k in kids if k in ix],
                       "groups": [gx[k] for k in kids if k in gx],
                       "padding": {"x": PAD, "y": TITLE, "X": PAD, "Y": PAD}})
    # WebCoLa takes a single number or nothing for padding on groups; use the mean
    for gr in groups:
        gr["padding"] = 22
    links = [{"source": ix[e.a], "target": ix[e.b],
              "d": 60 + (g.nodes[e.a].w + g.nodes[e.b].w) / 4} for e in g.edges]
    area = sum((n.w + GAP) * (n.h + GAP) for n in leaves)
    W = math.sqrt(area * 1.78) * 1.4
    data = {"nodes": [{"width": n.w + 12, "height": n.h + 12,
                       "x": (i * 97) % W, "y": (i * 53) % (W / 1.78)}
                      for i, n in enumerate(leaves)],
            "links": links, "groups": groups, "W": W, "H": W / 1.78, "flow": flow}
    out = json.loads(p3lib.run([p3lib.node(), "-e", COLA_SCRIPT,
                                p3lib.need(p3lib.COLA_JS, "webcola")], json.dumps(data), 180))
    pl = Place()
    for n, (x, y) in zip(leaves, out["nodes"], strict=True):
        pl.pos[n.id] = (x + 6, y + 6)
    fit_boxes(g, pl)  # own boxes: WebCoLa's padding has no title band
    pins_to_border(g, pl)
    _resolve_overlaps(g, pl)
    return pl


def _resolve_overlaps(g: PGraph, pl: Place, rounds: int = 40) -> None:
    """Push sibling containers / leaves apart where WebCoLa's soft group constraints left
    them overlapping, then refit boxes. Moves whole subtrees."""
    def subtree(nid: str) -> list[str]:
        if g.nodes[nid].kind != "container":
            return [nid]
        out = []
        for k in g.children.get(nid, []):
            out += subtree(k)
        return out

    def rect(nid: str):
        if nid in pl.boxes:
            return pl.boxes[nid]
        x, y = pl.pos[nid]
        return (x, y, g.nodes[nid].w, g.nodes[nid].h)

    for _ in range(rounds):
        moved = False
        for kids in g.children.values():
            kids = [k for k in kids if k in pl.pos or k in pl.boxes]
            for i, a in enumerate(kids):
                for b in kids[i + 1:]:
                    ra, rb = rect(a), rect(b)
                    ox = min(ra[0] + ra[2], rb[0] + rb[2]) - max(ra[0], rb[0]) + 12
                    oy = min(ra[1] + ra[3], rb[1] + rb[3]) - max(ra[1], rb[1]) + 12
                    if ox > 12 and oy > 12:
                        moved = True
                        if ox < oy:
                            dx = ox if rb[0] >= ra[0] else -ox
                            for k in subtree(b):
                                x, y = pl.pos[k]
                                pl.pos[k] = (x + dx, y)
                        else:
                            dy = oy if rb[1] >= ra[1] else -oy
                            for k in subtree(b):
                                x, y = pl.pos[k]
                                pl.pos[k] = (x, y + dy)
                        pl.boxes.clear()
                        fit_boxes(g, pl)
        if not moved:
            break


# ------------------------------------------------------------------ Graphviz
def place_graphviz(g: PGraph, prog: str) -> Place:
    inch = 72.0
    lines = ["digraph G {", "graph [compound=true, nodesep=0.5, ranksep=0.7, rankdir=LR, "
             "pack=true, packmode=\"array_u\", sep=\"+16\", esep=\"+8\"];",
             'node [shape=box, fixedsize=true, label=""];']

    def emit(nid: str, ind: str = "") -> None:
        n = g.nodes[nid]
        if n.kind == "container":
            lines.append(f'{ind}subgraph "cluster_{nid}" {{ label="{n.label}"; margin=22;')
            for k in g.children.get(nid, []):
                emit(k, ind + "  ")
            lines.append(f"{ind}}}")
        else:
            lines.append(f'{ind}"{nid}" [width={n.w / inch:.3f}, height={n.h / inch:.3f}];')

    for k in g.children[""]:
        emit(k)
    if prog == "dot":
        ins = [n.id for n in g.nodes.values() if n.kind == "pin" and n.side != "out"]
        outs = [n.id for n in g.nodes.values() if n.kind == "pin" and n.side == "out"]
        if ins:
            lines.append("{ rank=source; " + "; ".join(f'"{p}"' for p in ins) + " }")
        if outs:
            lines.append("{ rank=sink; " + "; ".join(f'"{p}"' for p in outs) + " }")
    for e in g.edges:
        lines.append(f'"{e.a}" -> "{e.b}";')
    lines.append("}")
    out = json.loads(p3lib.run([p3lib.gv(prog), "-Tjson"], "\n".join(lines), 180))
    H = float(out["bb"].split(",")[3])
    pl = Place()
    for o in out.get("objects", []):
        name = o.get("name", "")
        if name.startswith("cluster_"):
            if "bb" in o:
                x0, y0, x1, y1 = map(float, o["bb"].split(","))
                pl.boxes[name[8:]] = (x0, H - y1, x1 - x0, y1 - y0)
        elif name in g.nodes and "pos" in o:
            x, y = map(float, o["pos"].split(","))
            n = g.nodes[name]
            pl.pos[name] = (x - n.w / 2, H - y - n.h / 2)
    pl.boxes.clear()
    fit_boxes(g, pl)
    pins_to_border(g, pl)
    _resolve_overlaps(g, pl)
    return pl


# ------------------------------------------------------------------ level composition
@dataclass
class Item:
    id: str
    w: float
    h: float
    kind: str
    deg: int = 0


def compose(g: PGraph, level_engine, **kw) -> Place:
    """Bottom-up: lay out each container's children with `level_engine`, size it, go up."""
    size: dict[str, tuple[float, float]] = {}
    local: dict[str, dict[str, tuple[float, float]]] = {}
    notes: list[str] = []

    def depth(c: str) -> int:
        return 0 if c == "" else 1 + depth(g.nodes[c].parent)

    for cid in sorted(g.children, key=depth, reverse=True):
        kids = g.children[cid]
        if cid == "":
            kids = [k for k in kids if g.nodes[k].kind != "pin"]
        items = [Item(k, *(size[k] if k in size else (g.nodes[k].w, g.nodes[k].h)),
                      g.nodes[k].kind, g.nodes[k].deg) for k in kids]
        edges = level_edges(g, cid)
        here = {i.id for i in items}
        edges = [e for e in edges if e[0] in here and e[1] in here]
        pos = level_engine(g, cid, items, edges, notes, **kw) if items else {}
        if pos:
            mx = min(x for x, _y in pos.values())
            my = min(y for _x, y in pos.values())
            ox, oy = (PAD, TITLE) if cid else (0, 0)
            pos = {k: (x - mx + ox, y - my + oy) for k, (x, y) in pos.items()}
            w = max(pos[i.id][0] + i.w for i in items) + (PAD if cid else 0)
            h = max(pos[i.id][1] + i.h for i in items) + (PAD if cid else 0)
        else:
            w, h = 120, 60
        local[cid] = pos
        if cid:
            size[cid] = (w, h)
    pl = Place(notes=notes)

    def put(cid: str, X: float, Y: float) -> None:
        for k, (x, y) in local.get(cid, {}).items():
            if g.nodes[k].kind == "container":
                w, h = size[k]
                pl.boxes[k] = (X + x, Y + y, w, h)
                put(k, X + x, Y + y)
            else:
                pl.pos[k] = (X + x, Y + y)
    put("", 0, 0)
    for c in g.containers():
        if c.id not in pl.boxes:
            pl.boxes[c.id] = (0, 0, 120, 60)
    pins_to_border(g, pl)
    return pl


def _bfs_order(items: list[Item], edges) -> list[Item]:
    adj: dict[str, list[str]] = {i.id: [] for i in items}
    for a, b, _w in edges:
        adj[a].append(b)
        adj[b].append(a)
    by = {i.id: i for i in items}
    start = sorted(items, key=lambda i: (-len(adj[i.id]), i.id))
    seen, out = set(), []
    for s in start:
        if s.id in seen:
            continue
        q = deque([s.id])
        seen.add(s.id)
        while q:
            u = q.popleft()
            out.append(by[u])
            for v in sorted(adj[u], key=lambda v: -len(adj[v])):
                if v not in seen:
                    seen.add(v)
                    q.append(v)
    return out


def lvl_grid(g, cid, items, edges, notes, aspect: float = 1.78, **_kw):
    order = _bfs_order(items, edges)
    cw = sorted(i.w for i in order)[(3 * len(order)) // 4]
    total = sum(max(cw, i.w) + GAP for i in order)
    hmed = sorted(i.h for i in order)[len(order) // 2] + GAP
    per = max(1, round(math.sqrt(total * hmed * aspect) / (cw + GAP)))
    pos, y = {}, 0.0
    for r in range(0, len(order), per):
        row = order[r:r + per]
        x = 0.0
        for it in row:
            w = max(cw, it.w)
            pos[it.id] = (x + (w - it.w) / 2, y)
            x += w + GAP
        y += max(i.h for i in row) + GAP
    return pos


def lvl_busbar(g, cid, items, edges, notes, **_kw):
    bars = sorted((i for i in items if i.kind == "bar"), key=lambda i: -i.deg)
    if not bars:
        return lvl_grid(g, cid, items, edges, notes)
    barset = {b.id for b in bars}
    talk: dict[str, dict[str, float]] = {}
    for a, b, w in edges:
        for dev, hub in ((a, b), (b, a)):
            if hub in barset and dev not in barset:
                talk.setdefault(dev, {}).setdefault(hub, 0)
                talk[dev][hub] += w
    of: dict[str, list[Item]] = {b.id: [] for b in bars}
    free = []
    for it in items:
        if it.id in barset:
            continue
        if it.id in talk:
            of[max(talk[it.id], key=talk[it.id].get)].append(it)
        else:
            free.append(it)
    pos, y = {}, 0.0
    if free:
        x = 0.0
        for it in free:
            pos[it.id] = (x, y)
            x += it.w + GAP
        y += max(i.h for i in free) + GAP
    for bar in bars:
        devs = sorted(of[bar.id], key=lambda i: -i.deg)
        top, bot, wt, wb = [], [], 0.0, 0.0
        for it in devs:
            if wt <= wb:
                top.append(it)
                wt += it.w + GAP
            else:
                bot.append(it)
                wb += it.w + GAP
        cw = max([i.w for i in devs] + [0])
        cw = sorted([i.w for i in devs])[(3 * len(devs)) // 4] if devs else 0
        def row(lst, yy, cw=cw):
            x = 0.0
            for it in lst:
                w = max(cw, it.w)
                pos[it.id] = (x + (w - it.w) / 2, yy)
                x += w + GAP
            return x - GAP
        ht = max([i.h for i in top] + [0])
        r1 = row(top, y)
        yb = y + ht + (GAP if top else 0)
        r2 = row(bot, yb + bar.h + GAP)
        bar_w = max(r1, r2, bar.w)
        g.nodes[bar.id].w = bar_w  # the bar spans the row
        bar.w = bar_w
        pos[bar.id] = (0.0, yb)
        y = yb + bar.h + GAP + (max([i.h for i in bot] + [0]) + GAP if bot else 0) + GAP / 2
    return pos


def shrink(items: list[Item], pos: dict, gap: float = GAP) -> dict:
    """Scale centres towards their mean by the smallest factor that keeps every pair of
    items `gap` apart: keeps the engine's shape, removes its slack."""
    by = {i.id: i for i in items if i.id in pos}
    cen = {k: (x + by[k].w / 2, y + by[k].h / 2) for k, (x, y) in pos.items() if k in by}
    if len(cen) < 2:
        return pos
    mx = sum(c[0] for c in cen.values()) / len(cen)
    my = sum(c[1] for c in cen.values()) / len(cen)

    def ok(s: float) -> bool:
        ks = list(cen)
        for i, a in enumerate(ks):
            ax, ay = mx + (cen[a][0] - mx) * s, my + (cen[a][1] - my) * s
            for b in ks[i + 1:]:
                bx, by_ = mx + (cen[b][0] - mx) * s, my + (cen[b][1] - my) * s
                if (abs(ax - bx) < (by[a].w + by[b].w) / 2 + gap
                        and abs(ay - by_) < (by[a].h + by[b].h) / 2 + gap):
                    return False
        return True

    lo, hi = 0.05, 1.0
    if not ok(hi):
        return pos
    for _ in range(25):
        mid = (lo + hi) / 2
        if ok(mid):
            hi = mid
        else:
            lo = mid
    s = hi
    return {k: (mx + (c[0] - mx) * s - by[k].w / 2, my + (c[1] - my) * s - by[k].h / 2)
            for k, c in cen.items()}


def lvl_hola(g, cid, items, edges, notes, **_kw):
    if len(items) == 1:
        return {items[0].id: (0.0, 0.0)}
    ix = {it.id: k + 1 for k, it in enumerate(items)}
    back = {v: k for k, v in ix.items()}
    nodes = []
    R = 60 * len(items)
    for k, it in enumerate(items):
        a = 2 * math.pi * k / len(items)
        nodes.append(f"{ix[it.id]} {R * math.cos(a):.1f} {R * math.sin(a):.1f} "
                     f"{it.w + 20:.1f} {it.h + 20:.1f}")
    seen = set()
    es = []
    for a, b, _w in edges:
        k = tuple(sorted((ix[a], ix[b])))
        if k not in seen:
            seen.add(k)
            es.append(f"{k[0]} {k[1]}")
    tglf = "\n".join(nodes) + "\n#\n" + "\n".join(es) + "\n"
    last = None
    for growth in ("", "1", "2", "3"):
        try:
            out = p3lib.run([p3lib.need(p3lib.BIN / "hola_run", "hola_run"),
                             *([growth] if growth else [])], tglf, 120)
            break
        except RuntimeError as e:  # HOLA asserts on some graphs; try another tree direction
            last = e
    else:
        notes.append(f"hola failed on {cid or 'root'}: {str(last)[:80]}; grid used")
        return lvl_grid(g, cid, items, edges, notes)
    pos = {}
    for line in out.splitlines():
        f = line.split()
        if f and f[0] == "N":
            it = next(i for i in items if i.id == back[int(f[1])])
            cx, cy = float(f[2]), float(f[3])
            pos[it.id] = (cx - it.w / 2, cy - it.h / 2)
    pos = shrink(items, pos)
    # HOLA may leave isolated items on top of each other: shelf them below
    placed = [i for i in items if i.id in pos]
    missing = [i for i in items if i.id not in pos]
    if missing:
        y = max(pos[i.id][1] + i.h for i in placed) + GAP
        x = 0.0
        for it in missing:
            pos[it.id] = (x, y)
            x += it.w + GAP
    notes.append(f"hola {cid or 'root'}: {len(items)} items")
    return pos


def lvl_cpsat(g, cid, items, edges, notes, seconds: float = 20.0, **_kw):
    try:
        from ortools.sat.python import cp_model
    except ImportError as e:
        raise ValueError("ortools not installed (run with --with ortools)") from e
    if len(items) == 1:
        return {items[0].id: (0.0, 0.0)}
    C = 8.0
    n = len(items)
    span = sum(max(i.w, i.h) + GAP for i in items)
    gmax = int(span / C) + 1
    m = cp_model.CpModel()
    gx = [m.NewIntVar(0, gmax, f"x{k}") for k in range(n)]
    gy = [m.NewIntVar(0, gmax, f"y{k}") for k in range(n)]
    wc = [int(math.ceil((it.w + GAP) / C)) for it in items]
    hc = [int(math.ceil((it.h + GAP) / C)) for it in items]
    xi = [m.NewFixedSizeIntervalVar(gx[k], wc[k], f"xi{k}") for k in range(n)]
    yi = [m.NewFixedSizeIntervalVar(gy[k], hc[k], f"yi{k}") for k in range(n)]
    m.AddNoOverlap2D(xi, yi)
    W = m.NewIntVar(0, 2 * gmax, "W")
    H = m.NewIntVar(0, 2 * gmax, "H")
    for k in range(n):
        m.Add(W >= gx[k] + wc[k])
        m.Add(H >= gy[k] + hc[k])
    ix = {it.id: k for k, it in enumerate(items)}
    terms = []
    for a, b, w in edges:
        i, j = ix[a], ix[b]
        dx = m.NewIntVar(0, 4 * gmax, "")
        dy = m.NewIntVar(0, 4 * gmax, "")
        m.AddAbsEquality(dx, 2 * gx[i] + wc[i] - 2 * gx[j] - wc[j])
        m.AddAbsEquality(dy, 2 * gy[i] + hc[i] - 2 * gy[j] - hc[j])
        # reward a shared row (same top) or column (same left): the figures' alignment
        same_r = m.NewBoolVar("")
        same_c = m.NewBoolVar("")
        m.Add(gy[i] == gy[j]).OnlyEnforceIf(same_r)
        m.Add(gx[i] == gx[j]).OnlyEnforceIf(same_c)
        terms.append(int(w * 4) * (dx + dy) - 30 * (same_r + same_c))
    m.Minimize(sum(terms) + 6 * (W + H))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = seconds
    s.parameters.num_workers = 8
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        notes.append(f"cpsat {cid or 'root'} {s.StatusName(st)}; grid used")
        return lvl_grid(g, cid, items, edges, notes)
    obj = s.ObjectiveValue()
    gap = (obj - s.BestObjectiveBound()) / max(1, abs(obj))
    notes.append(f"cpsat {cid or 'root'} n={n} {s.StatusName(st)} gap={gap:.0%}")
    return {it.id: (s.Value(gx[k]) * C, s.Value(gy[k]) * C) for k, it in enumerate(items)}


ENGINES = {
    "elk": lambda g, **kw: place_elk(g),
    "cola": lambda g, **kw: place_cola(g),
    "dot": lambda g, **kw: place_graphviz(g, "dot"),
    "fdp": lambda g, **kw: place_graphviz(g, "fdp"),
    "osage": lambda g, **kw: place_graphviz(g, "osage"),
    "hola": lambda g, **kw: compose(g, lvl_hola),
    "busbar": lambda g, **kw: compose(g, lvl_busbar),
    "grid": lambda g, **kw: compose(g, lvl_grid),
    "cpsat": lambda g, **kw: compose(g, lvl_cpsat, **kw),
}
