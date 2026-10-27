"""ELK (elkjs 0.9.3) with per-node layout options: one JSON for the whole diagram.

Differences from e1's ext.place_elk:
- every node can carry its own `elk.algorithm` and `elk.hierarchyHandling` (X3: does the
  "root rectpacking, children layered" recursion work in one call?);
- an edge is declared in the lowest common ancestor of its endpoints and, when the root is
  not INCLUDE_CHILDREN, split at every container border with a pseudo-port on the
  container (ELK's documented way to draw hierarchy-crossing edges bottom-up);
- edges that come back without sections (rectpacking ignores edges) are routed afterwards
  with e1's A* on the ELK placement, and counted in `notes`.

Variants (names used by run.py):
  elk_inc    e1's baseline: layered, INCLUDE_CHILDREN, edges at the root
  elk_hd     elk_inc + highDegreeNodes.treatment (X2)
  elk_sep    layered everywhere, SEPARATE_CHILDREN (bottom-up inside ELK, X5)
  rect_root  root rectpacking, containers layered (X3)
  topdown    root rectpacking with top-down layout (ELK 0.9), containers layered (X3 probe)
"""

from __future__ import annotations

import json
import subprocess

from e1lib import Layout, Rect, Scene, U, ext, finish_placement, resize, route_astar

PAD = ext.ELK_BASE["elk.padding"]
LAYERED = {
    "elk.algorithm": "layered",
    "elk.direction": "RIGHT",
    "elk.edgeRouting": "ORTHOGONAL",
    "elk.spacing.nodeNode": 4 * U,
    "elk.layered.spacing.nodeNodeBetweenLayers": 6 * U,
    "elk.spacing.edgeEdge": U,
    "elk.spacing.edgeNode": 2 * U,
    "elk.layered.spacing.edgeEdgeBetweenLayers": U,
    "elk.layered.spacing.edgeNodeBetweenLayers": 2 * U,
    "elk.padding": PAD,
}
RECT = {
    "elk.algorithm": "rectpacking",
    "elk.aspectRatio": 1.78,
    "elk.spacing.nodeNode": 4 * U,
    "elk.padding": PAD,
    "elk.rectpacking.packing.strategy": "COMPACTION",
    "elk.rectpacking.whiteSpaceElimination.strategy": "TO_ASPECT_RATIO",
    "elk.expandNodes": False,
}
HD = {"elk.layered.highDegreeNodes.treatment": True,
      "elk.layered.highDegreeNodes.threshold": 6,
      "elk.layered.highDegreeNodes.treeHeight": 5}


def _variant(name: str):
    """(root options, container options, split edges at borders?)"""
    if name == "elk_inc":
        return {**LAYERED, "elk.hierarchyHandling": "INCLUDE_CHILDREN"}, {}, False
    if name == "elk_hd":
        return {**LAYERED, **HD, "elk.hierarchyHandling": "INCLUDE_CHILDREN"}, {}, False
    if name == "elk_sep":
        return ({**LAYERED, "elk.hierarchyHandling": "SEPARATE_CHILDREN"},
                {**LAYERED, "elk.hierarchyHandling": "SEPARATE_CHILDREN"}, True)
    if name == "rect_root":
        return ({**RECT, "elk.hierarchyHandling": "SEPARATE_CHILDREN"},
                {**LAYERED, "elk.hierarchyHandling": "INCLUDE_CHILDREN"}, True)
    if name == "topdown":
        return ({**RECT, "elk.hierarchyHandling": "SEPARATE_CHILDREN", "elk.topdownLayout": True,
                 "elk.topdown.nodeType": "ROOT_NODE"},
                {**LAYERED, "elk.hierarchyHandling": "INCLUDE_CHILDREN",
                 "elk.topdown.nodeType": "HIERARCHICAL_NODE",
                 "elk.topdown.hierarchicalNodeWidth": 60 * U,
                 "elk.topdown.hierarchicalNodeAspectRatio": 1.78}, True)
    raise KeyError(name)


VARIANTS = ("elk_inc", "elk_hd", "elk_sep", "rect_root", "topdown")
SIDE = {"W": "WEST", "E": "EAST", "N": "NORTH", "S": "SOUTH"}


def build(sc: Scene, variant: str) -> tuple[dict, dict]:
    """ELK JSON for the whole scene. Returns (graph, pieces) where pieces maps (net, target)
    to the list of edge ids that together draw that sink."""
    root_opts, cont_opts, split = _variant(variant)
    pseudo: dict[str, list[dict]] = {}  # container -> extra ports

    def ports_of(nid: str) -> list[dict]:
        out = []
        for pid, (dx, dy) in sc.poff.items():
            if sc.node_of[pid] == nid:
                out.append({"id": pid if nid != pid else f"{pid}#", "x": dx * U, "y": dy * U,
                            "width": 0, "height": 0,
                            "layoutOptions": {"elk.port.side": SIDE[sc.side[pid]]}})
        return out

    edges_in: dict[str, list[dict]] = {"": []}

    def node(nid: str) -> dict:
        if nid in sc.children:
            own = [{"id": p.id, "width": 0, "height": 0,
                    "layoutOptions": {"elk.port.side": "WEST" if sc.side[p.id] == "W" else "EAST"}}
                   for p in sc.ports.values() if p.owner_block_id == nid]
            edges_in.setdefault(nid, [])
            return {"id": nid, "children": [node(c) for c in sc.children[nid]],
                    "ports": own + pseudo.get(nid, []), "edges": edges_in[nid],
                    "layoutOptions": {**cont_opts, "elk.padding": PAD,
                                      "elk.portConstraints": "FIXED_SIDE"}}
        w, h = sc.size[nid]
        return {"id": nid, "width": w * U, "height": h * U, "ports": ports_of(nid),
                "layoutOptions": {"elk.portConstraints": "FIXED_POS"}}

    def path(pid: str) -> list[str]:
        """containers from the root down to the node that owns `pid` (exclusive of leaf)."""
        owner = sc.ports[pid].owner_block_id
        if owner is None:
            return []
        if owner in sc.children:  # a container's own port: the container is the node
            return sc.chain(owner)
        return sc.chain(owner)

    def ref(pid: str) -> str:
        return f"{pid}#" if pid in sc.pins else pid

    pieces: dict[tuple[str, str], list[str]] = {}
    for n in sc.wires:
        for t in n.targets:
            key = (n.id, t)
            ps, pt = path(n.source), path(t)
            k = 0
            while k < len(ps) and k < len(pt) and ps[k] == pt[k]:
                k += 1
            lca = ps[k - 1] if k else ""
            if not split:
                edges_in[""].append({"id": f"{n.id}|{t}|0", "sources": [ref(n.source)],
                                     "targets": [ref(t)]})
                pieces[key] = [f"{n.id}|{t}|0"]
                continue
            # climb from the source out to the LCA, then descend into the target
            ids = []
            cur = ref(n.source)
            up = ps[k:]  # containers the source side must leave, innermost last
            for c in reversed(up):
                pp = f"{n.id}|{t}@{c}"
                pseudo.setdefault(c, []).append(
                    {"id": pp, "width": 0, "height": 0, "layoutOptions": {"elk.port.side": "EAST"}})
                eid = f"{n.id}|{t}|{len(ids)}"
                edges_in.setdefault(c, []).append({"id": eid, "sources": [cur], "targets": [pp]})
                ids.append(eid)
                cur = pp
            down = pt[k:]  # containers the target side must enter, outermost first
            chain_down = []
            for c in down:
                pp = f"{n.id}|{t}@{c}"
                pseudo.setdefault(c, []).append(
                    {"id": pp, "width": 0, "height": 0, "layoutOptions": {"elk.port.side": "WEST"}})
                chain_down.append((c, pp))
            # edge at the LCA level: from `cur` to the first entry port (or the target)
            nxt = chain_down[0][1] if chain_down else ref(t)
            eid = f"{n.id}|{t}|{len(ids)}"
            edges_in.setdefault(lca, []).append({"id": eid, "sources": [cur], "targets": [nxt]})
            ids.append(eid)
            for i, (c, pp) in enumerate(chain_down):
                nxt = chain_down[i + 1][1] if i + 1 < len(chain_down) else ref(t)
                eid = f"{n.id}|{t}|{len(ids)}"
                edges_in.setdefault(c, []).append({"id": eid, "sources": [pp], "targets": [nxt]})
                ids.append(eid)
            pieces[key] = ids

    children = [node(b) for b in sc.children.get(None, [])]
    for pid in sc.pins:
        w, h = sc.size[pid]
        first = sc.ports[pid].direction == "input"
        children.append({"id": pid, "width": w * U, "height": h * U, "ports": ports_of(pid),
                         "layoutOptions": {"elk.portConstraints": "FIXED_POS",
                                           "elk.layered.layering.layerConstraint":
                                           "FIRST" if first else "LAST"}})
    graph = {"id": "root", "layoutOptions": root_opts, "children": children,
             "edges": edges_in[""]}
    return graph, pieces


def run(graph: dict, timeout: int = 120) -> dict:
    res = subprocess.run([ext._node(), str(ext.RUNNER), str(ext.ELK_JS)], input=json.dumps(graph),
                         capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"elk: {res.stderr.strip()[:300]}")
    return json.loads(res.stdout)


def read(sc: Scene, out: dict, pieces: dict, scaled: bool = False) -> Layout:
    """ELK output -> Layout. Pseudo-ports are dropped. Sinks whose pieces have no sections
    are routed by A* afterwards (`lay.notes` says how many)."""
    lay = Layout()
    origin: dict[str, tuple[float, float]] = {"root": (0.0, 0.0), "": (0.0, 0.0)}
    scale_of: dict[str, float] = {"root": 1.0, "": 1.0}
    edge_pts: dict[str, list] = {}

    def sections(e: dict, cont: str) -> list | None:
        ox, oy = origin.get(cont, (0.0, 0.0))
        s = scale_of.get(cont, 1.0)
        pts = []
        for sec in e.get("sections", []):
            for p in [sec["startPoint"], *sec.get("bendPoints", []), sec["endPoint"]]:
                pts.append(((ox + p["x"] * s) / U, (oy + p["y"] * s) / U))
        return pts or None

    def walk(n: dict, nid: str, ox: float, oy: float, s: float) -> None:
        own = float(n.get("layoutOptions", {}).get("org.eclipse.elk.topdown.scaleFactor", 1.0)) \
            if scaled else 1.0
        sub = s * own
        for c in n.get("children", []):
            x, y = ox + c["x"] * sub, oy + c["y"] * sub
            origin[c["id"]] = (x, y)
            scale_of[c["id"]] = sub
            if c["id"] in sc.children:
                lay.boxes[c["id"]] = Rect(x / U, y / U, c["width"] * sub / U, c["height"] * sub / U)
                for p in c.get("ports", []):
                    if "@" not in p["id"]:
                        lay.port_xy[p["id"]] = ((x + p["x"] * sub) / U, (y + p["y"] * sub) / U)
                walk(c, c["id"], x, y, sub)
            else:
                lay.pos[c["id"]] = (x / U, y / U)
                if scaled and abs(sub - 1.0) > 1e-6 and c["id"] in sc.blocks:
                    resize(sc, c["id"], round(c["width"] * sub / U), round(c["height"] * sub / U))
        for e in n.get("edges", []):
            edge_pts[e["id"]] = sections(e, e.get("container", nid))

    walk(out, "root", 0.0, 0.0, 1.0)
    finish_placement(sc, lay)
    missing = []
    for key, ids in pieces.items():
        parts = [edge_pts.get(i) for i in ids]
        if all(parts):
            pts = []
            for p in parts:
                pts += p
            lay.wires[key] = pts
        else:
            missing.append(key)
    if missing:
        nets = {k[0] for k in missing}
        keep = sc.wires
        sc.wires = [n for n in keep if n.id in nets]
        try:
            route_astar(sc, lay, order="class")
        finally:
            sc.wires = keep
        lay.notes.append(f"{len(missing)} sinks had no ELK route; A* on {len(nets)} nets")
    return lay


def place(sc: Scene, variant: str) -> Layout:
    graph, pieces = build(sc, variant)
    out = run(graph)
    return read(sc, out, pieces, scaled=variant == "topdown")
