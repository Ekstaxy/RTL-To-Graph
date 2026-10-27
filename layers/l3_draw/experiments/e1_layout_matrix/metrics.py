"""Geometry measurements on a finished layout (design-space Q3, N4).

Wires are orthogonal polylines. Per net, overlapping pieces of its own sinks are merged
first, so a shared trunk is counted once.

Hard violations (a drawing with any of these is wrong or misleading):
  unrouted   sinks with no orthogonal route
  through    (net, block) pairs where the wire runs through a block it does not end at
  overlap    pairs of nets that share a stretch of line
  touch      a wire ends or bends exactly on another net's wire (reads as a junction)
  block_ov   pairs of blocks that overlap
  box_viol   blocks sitting inside a container they do not belong to
Soft measures: crossings (and those involving a data net), bends, wire length, canvas.
"""

from __future__ import annotations

from model import NON_DATA, Layout, Scene, U, norm

EPS = 1e-6


def _merge(iv: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + EPS:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out if b - a > EPS]


def net_segments(lay: Layout) -> dict[str, tuple[list, list, int]]:
    """net id -> (H segments (y, x1, x2), V segments (x, y1, y2), diagonal count)."""
    hs: dict[str, dict[float, list]] = {}
    vs: dict[str, dict[float, list]] = {}
    diag: dict[str, int] = {}
    for (net, _t), pts in lay.wires.items():
        hs.setdefault(net, {})
        vs.setdefault(net, {})
        for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
            if abs(ay - by) < EPS:
                hs[net].setdefault(round(ay, 3), []).append((min(ax, bx), max(ax, bx)))
            elif abs(ax - bx) < EPS:
                vs[net].setdefault(round(ax, 3), []).append((min(ay, by), max(ay, by)))
            else:
                diag[net] = diag.get(net, 0) + 1
    out = {}
    for net in hs:
        h = [(y, a, b) for y, iv in hs[net].items() for a, b in _merge(iv)]
        v = [(x, a, b) for x, iv in vs[net].items() for a, b in _merge(iv)]
        out[net] = (h, v, diag.get(net, 0))
    return out


def measure(sc: Scene, lay: Layout) -> dict[str, float]:
    segs = net_segments(lay)
    cls = {n.id: norm(n.class_) for n in sc.nets}
    data = {nid: cls.get(nid, "") not in NON_DATA for nid in segs}
    H = [(y, a, b, net) for net, (h, _v, _d) in segs.items() for y, a, b in h]
    V = [(x, a, b, net) for net, (_h, v, _d) in segs.items() for x, a, b in v]

    cross = cross_data = touch = 0
    for y, a, b, n1 in H:
        for x, c, d, n2 in V:
            if n1 == n2 or x < a - EPS or x > b + EPS or y < c - EPS or y > d + EPS:
                continue
            if a + EPS < x < b - EPS and c + EPS < y < d - EPS:
                cross += 1
                cross_data += data[n1] or data[n2]
            else:
                touch += 1

    overlap = 0
    for lines in (H, V):
        by: dict[float, list] = {}
        for k, a, b, net in lines:
            by.setdefault(k, []).append((a, b, net))
        for items in by.values():
            items.sort()
            for i, (_a1, b1, n1) in enumerate(items):
                for a2, _b2, n2 in items[i + 1 :]:
                    if a2 >= b1 - EPS:
                        break
                    overlap += n1 != n2

    rects = {n: lay.rect(sc, n) for n in lay.pos}
    through = 0
    for h, v, _d in segs.values():
        hit = set()
        for nid, r in rects.items():
            for y, a, b in h:
                if r.y + EPS < y < r.y2 - EPS and min(b, r.x2) - max(a, r.x) > EPS:
                    hit.add(nid)
            for x, a, b in v:
                if r.x + EPS < x < r.x2 - EPS and min(b, r.y2) - max(a, r.y) > EPS:
                    hit.add(nid)
        through += len(hit)

    ids = list(rects)
    block_ov = 0
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            ra, rb = rects[a], rects[b]
            if (min(ra.x2, rb.x2) - max(ra.x, rb.x) > EPS
                    and min(ra.y2, rb.y2) - max(ra.y, rb.y) > EPS):
                block_ov += 1
    box_viol = 0
    for cid, r in lay.boxes.items():
        for nid, q in rects.items():
            inside = min(r.x2, q.x2) - max(r.x, q.x) > EPS and min(r.y2, q.y2) - max(r.y, q.y) > EPS
            if inside and cid not in (sc.chain(nid) if nid in sc.blocks else []):
                box_viol += 1

    bends = 0
    for h, v, _d in segs.values():
        ends_h = {(a, y) for y, a, _b in h} | {(b, y) for y, _a, b in h}
        ends_v = {(x, a) for x, a, _b in v} | {(x, b) for x, _a, b in v}
        bends += len({(round(x, 3), round(y, 3)) for x, y in ends_h}
                     & {(round(x, 3), round(y, 3)) for x, y in ends_v})
    length = sum(b - a for _k, a, b, _n in H) + sum(b - a for _k, a, b, _n in V)

    def path_bends(pts: list) -> int:
        n = 0
        for p, q, r in zip(pts, pts[1:], pts[2:], strict=False):
            n += (abs(p[0] - q[0]) < EPS) != (abs(q[0] - r[0]) < EPS)
        return n

    data_sinks = [(k, p) for k, p in lay.wires.items() if data.get(k[0], True)]
    straight = sum(path_bends(p) == 0 for _k, p in data_sinks)
    backward = sum(p[-1][0] < p[0][0] - EPS for _k, p in data_sinks)

    xs = [r.x for r in rects.values()] + [r.x2 for r in rects.values()]
    ys = [r.y for r in rects.values()] + [r.y2 for r in rects.values()]
    for r in lay.boxes.values():
        xs += [r.x, r.x2]
        ys += [r.y, r.y2]
    for pts in lay.wires.values():
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]
    w = (max(xs) - min(xs)) * U if xs else 0
    h = (max(ys) - min(ys)) * U if ys else 0
    diag = sum(d for _h, _v, d in segs.values())
    m = {
        "unrouted": max(lay.unrouted, diag),
        "through": through,
        "overlap": overlap,
        "touch": touch,
        "block_ov": block_ov,
        "box_viol": box_viol,
        "cross": cross,
        "cross_data": cross_data,
        "bends": bends,
        "length": round(length * U),
        "width": round(w),
        "height": round(h),
        "aspect": round(w / h, 2) if h else 0,
        "data_sinks": len(data_sinks),
        "straight": straight,
        "backward": backward,
    }
    m["hard"] = sum(m[k] for k in ("unrouted", "through", "overlap", "touch", "block_ov",
                                   "box_viol"))
    return m


def score(m: dict[str, float]) -> tuple:
    """Lexicographic: violations, crossings on data nets, all crossings, bends, length."""
    return (m["hard"], m["cross_data"], m["cross"], m["bends"], m["length"])
