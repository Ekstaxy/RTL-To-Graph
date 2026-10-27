"""Adapters for existing engines: ELK (elkjs 0.9.3 under Node) and Graphviz dot.

Both are optional. `available()` says which ones this machine has; they are installed
under runs/.tools/ (see README).

ELK places and routes; its routes can be kept (`native=True`) or thrown away so an own
router runs on ELK's placement. Graphviz is used for placement only: its orthogonal
router ignores ports (design-space document, section 1.2).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from model import GLOBAL, Layout, Rect, Scene, U, finish_placement, norm
from place import _hint_col

ROOT = Path(__file__).resolve().parents[4]
TOOLS = ROOT / "runs" / ".tools"
ELK_JS = TOOLS / "elk" / "node_modules" / "elkjs" / "lib" / "elk.bundled.js"
RUNNER = Path(__file__).with_name("elk_run.js")


def _node() -> str | None:
    try:
        import nodejs_wheel

        cand = Path(nodejs_wheel.__file__).parent / "bin" / "node"
        if cand.exists():
            return str(cand)
    except ImportError:
        pass
    return shutil.which("node")


def _dot() -> str | None:
    cand = TOOLS / "gv" / "bin" / "dot"
    return str(cand) if cand.exists() else os.environ.get("RTL2D_DOT") or shutil.which("dot")


def available() -> dict[str, bool]:
    return {"elk": bool(_node()) and ELK_JS.exists(), "dot": bool(_dot())}


ELK_BASE = {
    "elk.algorithm": "layered",
    "elk.direction": "RIGHT",
    "elk.edgeRouting": "ORTHOGONAL",
    "elk.hierarchyHandling": "INCLUDE_CHILDREN",
    "elk.spacing.nodeNode": 4 * U,
    "elk.layered.spacing.nodeNodeBetweenLayers": 6 * U,
    "elk.spacing.edgeEdge": U,
    "elk.spacing.edgeNode": 2 * U,
    "elk.layered.spacing.edgeEdgeBetweenLayers": U,
    "elk.layered.spacing.edgeNodeBetweenLayers": 2 * U,
    "elk.padding": f"[top={3 * U},left={2 * U},bottom={2 * U},right={2 * U}]",
}

ELK_VARIANTS: dict[str, dict[str, object]] = {
    "elk": {},
    "elk_ns": {"elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX"},
    "elk_mo": {"elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES"},
    "elk_part": {"elk.partitioning.activate": True},
    "elk_wrap": {"elk.layered.wrapping.strategy": "MULTI_EDGE", "elk.aspectRatio": 16 / 9},
}


def place_elk(sc: Scene, variant: str = "elk", native: bool = True) -> Layout:
    opts = {**ELK_BASE, **ELK_VARIANTS[variant]}
    part = variant == "elk_part"
    if part and not any(_hint_col(sc, b) is not None for b in sc.leaves):
        raise ValueError("no stage hints for this input")

    def ports_of(nid: str) -> list[dict]:
        w, h = sc.size[nid]
        out = []
        for pid, (dx, dy) in sc.poff.items():
            if sc.node_of[pid] == nid:
                side = {"W": "WEST", "E": "EAST", "N": "NORTH", "S": "SOUTH"}[sc.side[pid]]
                out.append(
                    {"id": pid if nid != pid else f"{pid}#", "x": dx * U, "y": dy * U,
                     "width": 0, "height": 0, "layoutOptions": {"elk.port.side": side}}
                )
        return out

    def node(nid: str) -> dict:
        if nid in sc.children:
            own = [
                {"id": p.id, "width": 0, "height": 0,
                 "layoutOptions": {"elk.port.side": "WEST" if sc.side[p.id] == "W" else "EAST"}}
                for p in sc.ports.values()
                if p.owner_block_id == nid
            ]
            return {
                "id": nid,
                "children": [node(c) for c in sc.children[nid]],
                "ports": own,
                "layoutOptions": {"elk.padding": ELK_BASE["elk.padding"],
                                  "elk.portConstraints": "FIXED_SIDE"},
            }
        w, h = sc.size[nid]
        lo: dict[str, object] = {"elk.portConstraints": "FIXED_POS"}
        if part and (col := _hint_col(sc, nid)) is not None:
            lo["elk.partitioning.partition"] = col + 1
        return {"id": nid, "width": w * U, "height": h * U, "ports": ports_of(nid),
                "layoutOptions": lo}

    children = [node(b) for b in sc.children.get(None, [])]
    for pid in sc.pins:
        w, h = sc.size[pid]
        first = sc.ports[pid].direction == "input"
        lo = {"elk.portConstraints": "FIXED_POS",
              "elk.layered.layering.layerConstraint": "FIRST" if first else "LAST"}
        if part:
            lo["elk.partitioning.partition"] = 0 if first else 10**6
        children.append({"id": pid, "width": w * U, "height": h * U, "ports": ports_of(pid),
                         "layoutOptions": lo})

    def ref(pid: str) -> str:
        return f"{pid}#" if pid in sc.pins else pid

    edges = [
        {"id": f"{n.id}|{t}", "sources": [ref(n.source)], "targets": [ref(t)]}
        for n in sc.wires
        for t in n.targets
    ]
    graph = {"id": "root", "layoutOptions": opts, "children": children, "edges": edges}
    res = subprocess.run(
        [_node(), str(RUNNER), str(ELK_JS)], input=json.dumps(graph),
        capture_output=True, text=True, timeout=120,
    )
    if res.returncode != 0:
        raise RuntimeError(f"elk: {res.stderr.strip()[:300]}")
    out = json.loads(res.stdout)

    lay = Layout()
    origin: dict[str, tuple[float, float]] = {"root": (0.0, 0.0)}

    def walk(n: dict, ox: float, oy: float) -> None:
        for c in n.get("children", []):
            x, y = ox + c["x"], oy + c["y"]
            origin[c["id"]] = (x, y)
            if c["id"] in sc.children:
                lay.boxes[c["id"]] = Rect(x / U, y / U, c["width"] / U, c["height"] / U)
                for p in c.get("ports", []):
                    lay.port_xy[p["id"]] = ((x + p["x"]) / U, (y + p["y"]) / U)
                walk(c, x, y)
            else:
                lay.pos[c["id"]] = (x / U, y / U)

    walk(out, 0.0, 0.0)
    if not native:  # own router follows: snap to the grid
        lay.pos = {k: (round(x), round(y)) for k, (x, y) in lay.pos.items()}
        lay.boxes = {k: Rect(round(r.x), round(r.y), round(r.w), round(r.h))
                     for k, r in lay.boxes.items()}
        lay.port_xy = {k: (round(x), round(y)) for k, (x, y) in lay.port_xy.items()}
    finish_placement(sc, lay)
    if native:
        for e in out.get("edges", []):
            net, target = e["id"].split("|")
            ox, oy = origin.get(e.get("container", "root"), (0.0, 0.0))
            pts = []
            for s in e.get("sections", []):
                for p in [s["startPoint"], *s.get("bendPoints", []), s["endPoint"]]:
                    pts.append(((ox + p["x"]) / U, (oy + p["y"]) / U))
            if pts:
                lay.wires[(net, target)] = pts
            else:
                lay.unrouted += 1
    return lay


def place_dot(sc: Scene) -> Layout:
    """Graphviz dot for positions only (rankdir=LR, fixed node sizes, clusters for hierarchy)."""
    inch = U / 72.0
    lines = ["digraph g {", "rankdir=LR; nodesep=0.45; ranksep=0.8;",
             "node [shape=box, fixedsize=true, label=\"\"];"]

    def emit(bid: str) -> None:
        if bid in sc.children:
            lines.append(f'subgraph "cluster_{bid}" {{ margin=18;')
            for c in sc.children[bid]:
                emit(c)
            lines.append("}")
        else:
            w, h = sc.size[bid]
            lines.append(f'"{bid}" [width={w * inch:.3f}, height={h * inch:.3f}];')

    for b in sc.children.get(None, []):
        emit(b)
    for group, rank in (("input", "source"), ("output", "sink")):
        pins = [p for p in sc.pins if sc.ports[p].direction == group]
        for p in pins:
            w, h = sc.size[p]
            lines.append(f'"{p}" [width={w * inch:.3f}, height={h * inch:.3f}];')
        if pins:
            lines.append(f"{{ rank={rank}; " + "; ".join(f'"{p}"' for p in pins) + " }")
    seen = set()
    for n in sc.wires:
        u = sc.place_node(n.source)
        for t in n.targets:
            v = sc.place_node(t)
            if u and v and u != v and (u, v) not in seen:
                seen.add((u, v))
                attr = " [constraint=false]" if norm(n.class_) in GLOBAL else ""
                lines.append(f'"{u}" -> "{v}"{attr};')
    lines.append("}")
    res = subprocess.run([_dot(), "-Tplain"], input="\n".join(lines), capture_output=True,
                         text=True, timeout=120)
    if res.returncode != 0:
        raise RuntimeError(f"dot: {res.stderr.strip()[:300]}")
    lay = Layout()
    height = 0.0
    for line in res.stdout.splitlines():
        f = line.split()
        if f[0] == "graph":
            height = float(f[3])
        elif f[0] == "node":
            name = f[1].strip('"')
            x, y, w, h = map(float, f[2:6])
            lay.pos[name] = (round((x - w / 2) / inch), round((height - y - h / 2) / inch))
    finish_placement(sc, lay)
    return lay
