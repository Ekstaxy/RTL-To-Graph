"""E-class level engine: regular arrays by procedure, not by a general layouter.

Members of a sidecar array sit on a grid of equal cells. Edges between members that run
along the second flow axis (south) move to N/S ports so the lattice reads as rows and
columns. Pins feeding a top-row member from above and a left-column member from the
left sit over / beside that member. Other items go to the right of the array.
"""

from __future__ import annotations

from compose import GAP, Level
from e1lib import Scene, relocate_port

GAPX, GAPY = GAP + 2, GAP + 1


def place_level(sc: Scene, lv: Level, side: dict, **_kw) -> None:
    items = {i.id: i for i in lv.items}
    arrays = [a for a in side.get("arrays", [])
              if all(m in items for row in a["members"] for m in row)]
    pos: dict[str, tuple[int, int]] = {}
    placed: set[str] = set()
    owner = {p.id: p.owner_block_id for p in sc.ports.values()}
    nets = {n.id: n for n in sc.wires}
    x0 = 0
    for a in arrays:
        rows = a["members"]
        at: dict[str, tuple[int, int]] = {m: (r, c) for r, row in enumerate(rows)
                                          for c, m in enumerate(row)}
        flows = a.get("flow", ["E", "S"])
        # ports that join vertical neighbours go S (source) / N (target); the same port
        # names on every member follow, so the top row's inputs come from above too
        vert: dict[str, str] = {}  # port name -> side
        if "S" in flows:
            for u, v, nid, _c in lv.edges:
                if u in at and v in at and at[v][0] == at[u][0] + 1:
                    n = nets[nid]
                    if owner.get(n.source) == u:
                        vert[n.source.rsplit(".", 1)[-1]] = "S"
                    for t in n.targets:
                        if owner.get(t) == v:
                            vert[t.rsplit(".", 1)[-1]] = "N"
            for m in at:
                for pid in list(sc.poff):
                    if sc.node_of[pid] == m and pid.rsplit(".", 1)[-1] in vert:
                        relocate_port(sc, pid, vert[pid.rsplit(".", 1)[-1]])
        for it in lv.items:
            if it.kind == "leaf":
                it.w, it.h = sc.size[it.id]
        cw = max(items[m].w for row in rows for m in row)
        ch = max(items[m].h for row in rows for m in row)
        y0 = 0
        for r, row in enumerate(rows):
            for c, m in enumerate(row):
                pos[m] = (x0 + c * (cw + GAPX) + (cw - items[m].w) // 2,
                          y0 + r * (ch + GAPY) + (ch - items[m].h) // 2)
                placed.add(m)
        x0 += len(rows[0]) * (cw + GAPX) + GAP
    # pins: inputs on the left of the row they feed / above the column they feed
    for it in lv.items:
        if it.kind != "pin":
            continue
        pid = it.id
        n = next((n for n in sc.wires if pid in (n.source, *n.targets)), None)
        other = None
        if n is not None:
            ends = [n.source, *n.targets]
            other = next((owner.get(e) for e in ends if owner.get(e) in placed), None)
        if other is None:
            continue
        ox, oy = pos[other]
        inp = sc.ports[pid].direction == "input"
        tgt_port = next((e for e in [n.source, *n.targets] if owner.get(e) == other), None)
        if tgt_port and sc.side[tgt_port] in "NS":
            relocate_port(sc, pid, "S" if inp else "N", it.w // 2)
            it.w, it.h = sc.size[pid]
            pos[pid] = (ox + items[other].w // 2 - it.w // 2,
                        oy - it.h - GAP if inp else oy + items[other].h + GAP)
        else:
            pos[pid] = (ox - it.w - GAP if inp else ox + items[other].w + GAP,
                        oy + items[other].h // 2 - it.h // 2)
        placed.add(pid)
    y = 0
    for it in lv.items:  # anything else: a column on the right
        if it.id not in pos:
            pos[it.id] = (x0 + GAP, y)
            y += it.h + GAP
    lv.pos = pos
    lv.notes.append(f"arrays {[a['id'] for a in arrays]}")
