"""Class-specific measures on top of e1's metrics.measure (memo §5.1 step 4).

  align       share of leaves that share a row (top or centre y) or a column (left or
              centre x) with a sibling; 1.0 is a perfect grid
  compact     sum of leaf areas / area of the bounding box of leaves and containers
  aspect_err  |log2((W/H) / target)| of that bounding box, target 16:9
  bar_bypass  not computed here (busbar engine notes)

score_for(cls, m): lexicographic tuple, smaller is better. Ratios are rounded to one
decimal so that ties fall through to the next criterion.
"""

from __future__ import annotations

import math

from e1lib import Layout, Scene


def extra(sc: Scene, lay: Layout, target: float = 16 / 9) -> dict[str, float]:
    rects = {n: lay.rect(sc, n) for n in lay.pos if n in sc.blocks}
    parent = {b.id: b.parent_id for b in sc.blocks.values()}
    sib: dict[str | None, list[str]] = {}
    for n in rects:
        sib.setdefault(parent[n], []).append(n)
    hits, count = 0.0, 0
    for group in sib.values():
        if len(group) < 2:
            continue
        tops = [round(rects[n].y, 3) for n in group]
        cys = [round(rects[n].y + rects[n].h / 2, 3) for n in group]
        lefts = [round(rects[n].x, 3) for n in group]
        cxs = [round(rects[n].x + rects[n].w / 2, 3) for n in group]
        for i in range(len(group)):
            row = tops.count(tops[i]) > 1 or cys.count(cys[i]) > 1
            col = lefts.count(lefts[i]) > 1 or cxs.count(cxs[i]) > 1
            hits += (row + col) / 2
            count += 1
    align = hits / count if count else 1.0
    xs = [r.x for r in rects.values()] + [r.x2 for r in rects.values()]
    ys = [r.y for r in rects.values()] + [r.y2 for r in rects.values()]
    for r in lay.boxes.values():
        xs += [r.x, r.x2]
        ys += [r.y, r.y2]
    if xs:
        W, H = max(xs) - min(xs), max(ys) - min(ys)
        area = sum(r.w * r.h for r in rects.values())
        compact = area / (W * H) if W * H else 1.0
        aspect_err = abs(math.log2((W / H) / target)) if W and H else 0.0
    else:
        compact, aspect_err = 1.0, 0.0
    out = {"align": round(align, 3), "compact": round(compact, 3),
           "aspect_err": round(aspect_err, 3)}
    # per-container compactness, for the report
    for cid, box in lay.boxes.items():
        kids = [rects[n] for n in rects if parent[n] == cid]
        if kids and box.w * box.h:
            out[f"compact:{cid}"] = round(sum(r.w * r.h for r in kids) / (box.w * box.h), 3)
    return out


def score_for(cls: str, m: dict) -> tuple:
    r1 = lambda v: round(v, 1)  # noqa: E731
    if cls in ("A", "B", "AB"):
        return (m["hard"], m["cross_data"], m["cross"], m["bends"], m["length"])
    if cls == "C":
        return (m["hard"], m["cross_data"], m["cross"], -r1(m["compact"]), m["bends"], m["length"])
    if cls == "D":
        return (m["hard"], m["cross"], -r1(m["align"]), -r1(m["compact"]), m["length"])
    if cls == "E":
        return (m["hard"], -r1(m["align"]), r1(m["aspect_err"]), m["cross"], m["length"])
    return (m["hard"], m["cross_data"], m["cross"], m["bends"], m["length"])
