"""ELK layered as a *level* engine for compose: places the items of one container.

Leaves keep their fixed-position ports; sub-containers are plain boxes of the size pass 1
gave them; boundary pins get FIRST/LAST layer constraints. Routes are not used (compose
routes globally), so only positions are read back.
"""

from __future__ import annotations

import elkx
from compose import Level
from e1lib import Scene, U

SIDE = {"W": "WEST", "E": "EAST", "N": "NORTH", "S": "SOUTH"}


def place_level(sc: Scene, lv: Level, side: dict, **_kw) -> None:
    nodes = []
    for it in lv.items:
        n: dict = {"id": it.id, "width": it.w * U, "height": it.h * U, "layoutOptions": {}}
        if it.kind == "leaf" or it.kind == "pin":
            ports = []
            for pid, (dx, dy) in sc.poff.items():
                if sc.node_of[pid] == it.id:
                    ports.append({"id": pid if it.kind == "leaf" else f"{pid}#",
                                  "x": dx * U, "y": dy * U, "width": 0, "height": 0,
                                  "layoutOptions": {"elk.port.side": SIDE[sc.side[pid]]}})
            n["ports"] = ports
            n["layoutOptions"]["elk.portConstraints"] = "FIXED_POS"
        if it.kind == "pin":
            first = sc.ports[it.id].direction == "input"
            n["layoutOptions"]["elk.layered.layering.layerConstraint"] = (
                "FIRST" if first else "LAST")
        nodes.append(n)
    kinds = {it.id: it.kind for it in lv.items}
    owner = {p.id: p.owner_block_id for p in sc.ports.values()}

    def end(item: str, pid: str) -> str:
        if kinds[item] == "leaf" and owner.get(pid) == item:
            return pid
        if kinds[item] == "pin":
            return f"{pid}#"
        return item  # container: node-level endpoint

    nets = {n.id: n for n in sc.wires}
    edges = []
    for k, (u, v, nid, _c) in enumerate(lv.edges):
        n = nets[nid]
        tgt = next((t for t in n.targets if owner.get(t) == v or t == v
                    or (kinds[v] == "container" and t in sc.ports)), n.targets[0])
        edges.append({"id": f"e{k}", "sources": [end(u, n.source)], "targets": [end(v, tgt)]})
    graph = {"id": "root", "layoutOptions": {**elkx.LAYERED, "elk.hierarchyHandling":
                                             "INCLUDE_CHILDREN"},
             "children": nodes, "edges": edges}
    out = elkx.run(graph)
    for c in out.get("children", []):
        lv.pos[c["id"]] = (round(c["x"] / U), round(c["y"] / U))
