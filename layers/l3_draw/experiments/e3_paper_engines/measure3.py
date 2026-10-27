"""Measures for paper-style drawings (px). Hard violations first, then the D/C criteria.

hard: overlapping units, a unit drawn inside a container it does not belong to, sibling
      containers overlapping, a line through a unit it does not end at, two different
      lines sharing a stretch (collinear overlap)
soft: crossings, bends, length, align (siblings sharing a row or column), compact
      (unit area / drawing area), aspect error from 16:9, canvas size
"""

from __future__ import annotations

import math

from grammar import PGraph
from layout import Place

EPS = 0.5


def _segs(pts):
    return list(zip(pts, pts[1:], strict=False))


def measure(g: PGraph, pl: Place, routes: dict) -> dict:
    rect = {k: (x, y, g.nodes[k].w, g.nodes[k].h) for k, (x, y) in pl.pos.items()}

    def inter(a, b, m=0.0):
        return (min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) > m
                and min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) > m)

    ids = list(rect)
    node_ov = sum(inter(rect[a], rect[b], 1) for i, a in enumerate(ids) for b in ids[i + 1:])
    box_viol = 0
    for cid, bx in pl.boxes.items():
        for k, r in rect.items():
            if inter(bx, r, 1) and cid not in g.chain(k):
                box_viol += 1
    cont_ov = 0
    for kids in g.children.values():
        cs = [k for k in kids if k in pl.boxes]
        cont_ov += sum(inter(pl.boxes[a], pl.boxes[b], 1)
                       for i, a in enumerate(cs) for b in cs[i + 1:])
    H, V = [], []
    for eid, pts in routes.items():
        for (ax, ay), (bx, by) in _segs(pts):
            if abs(ay - by) < EPS:
                H.append((ay, min(ax, bx), max(ax, bx), eid))
            elif abs(ax - bx) < EPS:
                V.append((ax, min(ay, by), max(ay, by), eid))
    ends = {e.id: (e.a, e.b) for e in g.edges}
    through = 0
    for y, a, b, eid in H:
        for k, r in rect.items():
            if k in ends[eid]:
                continue
            if r[1] + EPS < y < r[1] + r[3] - EPS and min(b, r[0] + r[2]) - max(a, r[0]) > EPS:
                through += 1
    for x, a, b, eid in V:
        for k, r in rect.items():
            if k in ends[eid]:
                continue
            if r[0] + EPS < x < r[0] + r[2] - EPS and min(b, r[1] + r[3]) - max(a, r[1]) > EPS:
                through += 1
    cross = 0
    for y, a, b, e1 in H:
        for x, c, d, e2 in V:
            if e1 != e2 and a + EPS < x < b - EPS and c + EPS < y < d - EPS:
                cross += 1
    overlap = 0
    for lines in (H, V):
        by: dict[float, list] = {}
        for k, a, b, e in lines:
            by.setdefault(round(k, 1), []).append((a, b, e))
        for items in by.values():
            items.sort()
            for i, (_a, b1, e1) in enumerate(items):
                for a2, _b2, e2 in items[i + 1:]:
                    if a2 >= b1 - EPS:
                        break
                    overlap += e1 != e2
    bends = sum(max(0, len(p) - 2) for p in routes.values())
    length = sum(math.hypot(bx - ax, by - ay)
                 for p in routes.values() for (ax, ay), (bx, by) in _segs(p))
    # alignment among siblings (units and containers)
    hits = cnt = 0.0
    for kids in g.children.values():
        rs = [rect[k] if k in rect else pl.boxes.get(k) for k in kids
              if g.nodes[k].kind != "pin" and (k in rect or k in pl.boxes)]
        if len(rs) < 2:
            continue
        tops = [round(r[1]) for r in rs]
        cys = [round(r[1] + r[3] / 2) for r in rs]
        lefts = [round(r[0]) for r in rs]
        cxs = [round(r[0] + r[2] / 2) for r in rs]
        for i in range(len(rs)):
            row = any(abs(tops[i] - tops[j]) <= 2 or abs(cys[i] - cys[j]) <= 2
                      for j in range(len(rs)) if j != i)
            col = any(abs(lefts[i] - lefts[j]) <= 2 or abs(cxs[i] - cxs[j]) <= 2
                      for j in range(len(rs)) if j != i)
            hits += (row + col) / 2
            cnt += 1
    allr = list(rect.values()) + list(pl.boxes.values())
    X0 = min(r[0] for r in allr)
    Y0 = min(r[1] for r in allr)
    X1 = max(r[0] + r[2] for r in allr)
    Y1 = max(r[1] + r[3] for r in allr)
    W, Hh = X1 - X0, Y1 - Y0
    area = sum(r[2] * r[3] for k, r in rect.items() if g.nodes[k].kind != "pin")
    m = {"node_ov": node_ov, "box_viol": box_viol, "cont_ov": cont_ov, "through": through,
         "overlap": overlap, "cross": cross, "bends": bends, "length": round(length),
         "align": round(hits / cnt, 3) if cnt else 1.0,
         "compact": round(area / (W * Hh), 3) if W * Hh else 1.0,
         "aspect_err": round(abs(math.log2((W / Hh) / (16 / 9))), 3) if W and Hh else 0,
         "width": round(W), "height": round(Hh), "edges": len(g.edges)}
    m["hard"] = m["node_ov"] + m["box_viol"] + m["cont_ov"] + m["through"] + m["overlap"]
    return m


def score(m: dict) -> tuple:
    r1 = lambda v: round(v, 1)  # noqa: E731
    return (m["hard"], m["cross"], -r1(m["align"]), -r1(m["compact"]), r1(m["aspect_err"]),
            m["bends"], m["length"])
