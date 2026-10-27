"""Own routers. Both take a finished placement and fill `lay.wires`.

- `naive`: H-V-H elbows on a per-net track, no obstacle avoidance. Baseline that shows
  what a placement alone gives.
- `astar`: sequential maze routing on the unit grid (in the spirit of libavoid, R2).
  Each net is grown as a tree from its source. Rules on the grid:
    * nothing runs inside a block or within one unit of it, except straight out of a port;
    * two nets never share a grid edge, and never meet at a bend or a junction;
    * two nets may cross at a point if both go straight through; that costs `cross`;
    * the three cells straight out of every port are reserved: other nets may cross them
      but not run along them or bend there (otherwise early nets wall ports in).
  If a net cannot be routed, everything is ripped up and the failed nets go first (up to
  three times).
  `order` decides who routes first; `passes` > 1 rips up and re-routes every net once more.
"""

from __future__ import annotations

import heapq
from math import ceil, floor

from model import NON_DATA, Layout, Scene, escape, norm

DIRS = ((1, 0, 1), (-1, 0, 1), (0, 1, 2), (0, -1, 2))  # dx, dy, orientation bit (1=H, 2=V)


def _terminals(sc: Scene, lay: Layout):
    """(net, source port, [target ports]) for nets that have positions for both ends."""
    out = []
    for n in sc.wires:
        if n.source not in lay.port_xy:
            continue
        ts = [t for t in n.targets if t in lay.port_xy]
        if ts:
            out.append((n, n.source, ts))
    return out


def simplify(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in pts:
        if out and out[-1] == p:
            continue
        if len(out) >= 2:
            (ax, ay), (bx, by) = out[-2], out[-1]
            if (ax == bx == p[0]) or (ay == by == p[1]):
                out[-1] = p
                continue
        out.append(p)
    return out


def route_naive(sc: Scene, lay: Layout) -> None:
    top = min((p[1] for p in lay.pos.values()), default=0)
    for k, (n, src, targets) in enumerate(_terminals(sc, lay)):
        s, se = lay.port_xy[src], escape(sc, lay, src)
        off = 1 + k % 6
        for t in targets:
            p, pe = lay.port_xy[t], escape(sc, lay, t)
            if pe[0] > se[0] + off or sc.side[t] in "NS":
                xm = se[0] + off
                mid = [(xm, se[1]), (xm, pe[1])]
            else:  # target is behind the source: go over the top
                ya = top - 2 - k % 8
                mid = [(se[0] + off, se[1]), (se[0] + off, ya), (pe[0] - off, ya),
                       (pe[0] - off, pe[1])]
            lay.wires[(n.id, t)] = simplify([s, se, *mid, pe, p])


class _Grid:
    def __init__(self, sc: Scene, lay: Layout, margin: int) -> None:
        rects = [lay.rect(sc, n) for n in lay.pos]
        pts = list(lay.port_xy.values())
        xs = [r.x for r in rects] + [r.x2 for r in rects] + [p[0] for p in pts] or [0]
        ys = [r.y for r in rects] + [r.y2 for r in rects] + [p[1] for p in pts] or [0]
        self.ox, self.oy = floor(min(xs)) - margin, floor(min(ys)) - margin
        self.w = ceil(max(xs)) + margin - self.ox + 1
        self.h = ceil(max(ys)) + margin - self.oy + 1
        self.blocked = bytearray(self.w * self.h)
        for r in rects:
            for yy in range(floor(r.y) - 1, ceil(r.y2) + 2):
                base = (yy - self.oy) * self.w - self.ox
                for xx in range(floor(r.x) - 1, ceil(r.x2) + 2):
                    self.blocked[base + xx] = 1
        self.allow: dict[int, int] = {}  # cell -> net index allowed in spite of `blocked`
        self.occ: dict[int, dict[int, int]] = {}  # cell -> {net index: orientation mask}

    def idx(self, x: float, y: float) -> int:
        return (int(round(y)) - self.oy) * self.w + int(round(x)) - self.ox

    def xy(self, i: int) -> tuple[int, int]:
        return (i % self.w + self.ox, i // self.w + self.oy)


def route_astar(
    sc: Scene,
    lay: Layout,
    order: str = "short",
    passes: int = 1,
    bend: int = 3,
    cross: int = 12,
) -> None:
    terms = _terminals(sc, lay)
    g = _Grid(sc, lay, margin=6 + min(20, len(terms) // 2))
    W, H = g.w, g.h
    blocked, allow, occ = g.blocked, g.allow, g.occ
    cls = [norm(n.class_) for n, _s, _t in terms]
    is_data = [c not in NON_DATA for c in cls]
    esc: dict[str, int] = {}
    resv: dict[int, tuple[int, int]] = {}  # cell -> (net index, orientation of the port axis)
    for k, (_n, src, targets) in enumerate(terms):
        for pid in (src, *targets):
            e = escape(sc, lay, pid)
            esc[pid] = g.idx(*e)
            allow[esc[pid]] = k
            for dist in (2, 3):
                x, y = escape(sc, lay, pid, dist)
                c = g.idx(x, y)
                if 0 <= c < len(blocked) and not blocked[c]:
                    resv.setdefault(c, (k, 1 if sc.side[pid] in "WE" else 2))

    def span(k: int) -> float:
        _n, src, targets = terms[k]
        xs = [lay.port_xy[p][0] for p in (src, *targets)]
        ys = [lay.port_xy[p][1] for p in (src, *targets)]
        return (max(xs) - min(xs)) + (max(ys) - min(ys))

    ids = list(range(len(terms)))
    if order == "short":
        ids.sort(key=lambda k: (span(k), k))
    elif order == "long":
        ids.sort(key=lambda k: (-span(k), k))
    elif order == "class":  # data first (they get the straight tracks), then by length
        ids.sort(key=lambda k: (not is_data[k], span(k), k))

    parent: list[dict[int, int]] = [{} for _ in terms]  # per net: cell -> previous cell

    def search(k: int, starts: dict[int, int], goal: int) -> list[int] | None:
        gx, gy = goal % W, goal // W
        best: dict[tuple[int, int], int] = {}
        came: dict[tuple[int, int], tuple[int, int]] = {}
        heap: list[tuple[int, int, int, int]] = []
        for s in starts:
            best[(s, 0)] = 0
            heapq.heappush(heap, (abs(s % W - gx) + abs(s // W - gy), 0, s, 0))
        while heap:
            _f, cost, cell, d = heapq.heappop(heap)
            if cell == goal:
                path, st = [cell], (cell, d)
                while st in came:
                    st = came[st]
                    path.append(st[0])
                return path[::-1]
            if best.get((cell, d), 1 << 60) < cost:
                continue
            x, y = cell % W, cell // W
            others = occ.get(cell)
            foreign = [m for j, m in others.items() if j != k] if others else []
            if cell in resv and resv[cell][0] != k and resv[cell][0] not in (others or ()):
                foreign = [*foreign, resv[cell][1]]
            for dx, dy, o in DIRS:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < W and 0 <= ny < H):
                    continue
                nc = ny * W + nx
                if blocked[nc] and allow.get(nc) != k:
                    continue
                if blocked[nc] and nc != goal and nc not in starts:
                    continue
                step = 1
                if foreign:
                    # May only pass straight through, across nets that pass straight too.
                    if d != o or any(m != 3 - o for m in foreign):
                        continue
                    step += cross * len(foreign)
                    if is_data[k]:
                        step += cross
                if d and d != o:
                    step += bend
                nd = (nc, o)
                c2 = cost + step
                if c2 < best.get(nd, 1 << 60):
                    best[nd] = c2
                    came[nd] = (cell, d)
                    heapq.heappush(heap, (c2 + abs(nx - gx) + abs(ny - gy), c2, nc, o))
        return None

    def mark(k: int, path: list[int]) -> None:
        for a, b in zip(path, path[1:], strict=False):
            o = 1 if a // W == b // W else 2
            for c in (a, b):
                cell = occ.setdefault(c, {})
                cell[k] = cell.get(k, 0) | o
            parent[k].setdefault(b, a)

    def unmark(k: int) -> None:
        for c in list(parent[k]) + list(parent[k].values()):
            if c in occ and k in occ[c]:
                del occ[c][k]
                if not occ[c]:
                    del occ[c]
        parent[k].clear()

    def route_net(k: int) -> int:
        """Route every sink of net k; returns the number of sinks left unrouted."""
        _n, src, targets = terms[k]
        root = esc[src]
        tree = {root: 0}
        sx, sy = lay.port_xy[src]
        failed = 0
        todo = sorted(
            targets, key=lambda t: abs(lay.port_xy[t][0] - sx) + abs(lay.port_xy[t][1] - sy)
        )
        for t in todo:
            # Branch only from tree cells no other net touches.
            starts = {c: 0 for c in tree if len(occ.get(c, {})) <= 1}
            path = search(k, starts or {root: 0}, esc[t])
            if path is None:
                failed += 1
                continue
            mark(k, path)
            tree.update({c: 0 for c in path})
        return failed

    def cost_of(k: int) -> int:
        cells = set(parent[k]) | set(parent[k].values())
        x = sum(len(occ.get(c, {})) - 1 for c in cells)
        return len(parent[k]) + cross * x

    failed = {k: route_net(k) for k in ids}
    for _ in range(3):
        bad = [k for k in ids if failed[k]]
        if not bad:
            break
        for k in ids:
            unmark(k)
        ids = bad + [k for k in ids if not failed[k]]
        failed = {k: route_net(k) for k in ids}
    for _ in range(passes - 1):
        for k in ids:
            before, old = cost_of(k), dict(parent[k])
            was_failed = failed[k]
            unmark(k)
            now_failed = route_net(k)
            if (now_failed, cost_of(k)) > (was_failed, before):
                unmark(k)  # keep the old route
                for b, a in old.items():
                    mark(k, [a, b])
            else:
                failed[k] = now_failed

    for k, (n, src, targets) in enumerate(terms):
        root = esc[src]
        for t in targets:
            cell, cells = esc[t], []
            while cell != root and cell in parent[k] and len(cells) < W * H:
                cells.append(cell)
                cell = parent[k][cell]
            if cell != root:
                lay.wires[(n.id, t)] = [lay.port_xy[src], lay.port_xy[t]]
                lay.unrouted += 1
                continue
            pts = [g.xy(c) for c in [*cells, root][::-1]]
            lay.wires[(n.id, t)] = simplify([lay.port_xy[src], *pts, lay.port_xy[t]])


ROUTERS = {
    "naive": lambda sc, lay: route_naive(sc, lay),
    "astar": lambda sc, lay: route_astar(sc, lay, order="short"),
    "astar_cls": lambda sc, lay: route_astar(sc, lay, order="class"),
    "astar_cls2": lambda sc, lay: route_astar(sc, lay, order="class", passes=2),
}
