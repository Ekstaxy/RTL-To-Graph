"""Own placers. One layered (Sugiyama-style) engine with switches:

- `cyc`:   how cycles are broken: "dfs" (plain), "class" (data edges decide the order,
           control/status edges that go against it become feedback), "hints" (flow_role).
- `lane`:  pull controller-like blocks into a row above the datapath:
           None, "infer" (from kind/class), "hints" (lane == "control").
- `cols`:  "longest" (longest-path layering) or "hints" (stage_index / stage_boundary).
- `wrap`:  None or a target aspect ratio; layers are folded into rows to approach it.

`lay` = dfs, no lane, longest.            (design-space N1, own implementation)
`lay_ctl` = class + inferred lane.        (D4: semantics inferred inside L3)
`grid` = hints for everything.            (N2: stage x lane grid)
`*_wrap` = same, folded to 16:9.          (N3: fixed canvas)
"""

from __future__ import annotations

from statistics import median

from model import NON_DATA, Layout, Scene, finish_placement, norm

GAP = 4  # vertical gap between blocks: one free routing row between their keep-out rings


def _edges(sc: Scene) -> list[tuple[str, str, str, str, str, str]]:
    """(u, v, net id, class, source port, target port) per sink, node level, no self loops."""
    out = []
    for n in sc.wires:
        u = sc.place_node(n.source)
        for t in n.targets:
            v = sc.place_node(t)
            if u and v and u != v:
                out.append((u, v, n.id, norm(n.class_), n.source, t))
    return out


def _lane_nodes(sc: Scene, edges, lane: str | None) -> set[str]:
    if lane is None:
        return set()
    out = set()
    for bid in sc.leaves:
        if sc.blocks[bid].parent_id is not None:
            continue  # a lane block would stretch its container over the whole drawing
        if lane == "hints":
            if sc.hint(bid).get("lane") == "control":
                out.add(bid)
            continue
        outs = [e for e in edges if e[0] == bid]
        ctl = [e for e in outs if e[3] in NON_DATA]
        kind = norm(sc.blocks[bid].kind)
        if kind in {"controller", "fsm"} or (len(outs) >= 3 and len(ctl) == len(outs)):
            out.add(bid)
    return out


def _hint_col(sc: Scene, bid: str) -> int | None:
    h = sc.hint(bid) if bid in sc.blocks else {}
    if isinstance(h.get("stage_index"), int):
        return 2 * h["stage_index"]
    if isinstance(h.get("stage_boundary"), int):
        return 2 * h["stage_boundary"] + 1
    return None


def _break_cycles(sc: Scene, nodes: list[str], edges, cyc: str) -> set[int]:
    """Indices of edges to treat as reversed (feedback)."""
    rev: set[int] = set()
    if cyc == "hints":
        rev = {i for i, e in enumerate(edges) if sc.is_feedback(e[2], e[5])}
    elif cyc == "class":
        data = [i for i, e in enumerate(edges) if e[3] not in NON_DATA]
        drev = _dfs_back(nodes, edges, data, set())
        rank = _longest(nodes, edges, [i for i in data if i not in drev], drev)
        ranked = {n for i in data for n in edges[i][:2]}
        rev = set(drev)
        for i, e in enumerate(edges):
            if e[3] in NON_DATA and {e[0], e[1]} <= ranked and rank[e[0]] > rank[e[1]]:
                rev.add(i)
    live = [i for i in range(len(edges)) if i not in rev]
    return rev | _dfs_back(nodes, edges, live, rev)


def _dfs_back(nodes: list[str], edges, use: list[int], rev: set[int]) -> set[int]:
    adj: dict[str, list[tuple[str, int]]] = {n: [] for n in nodes}
    for i in use:
        u, v = edges[i][0], edges[i][1]
        if u in adj and v in adj:
            adj[u].append((v, i))
    for i in rev:  # already reversed edges still constrain, in the other direction
        u, v = edges[i][1], edges[i][0]
        if u in adj and v in adj:
            adj[u].append((v, -1))
    state: dict[str, int] = {}
    back: set[int] = set()
    for root in nodes:
        if root in state:
            continue
        stack = [(root, iter(adj[root]))]
        state[root] = 1
        while stack:
            node, it = stack[-1]
            for v, i in it:
                if state.get(v) == 1:
                    if i >= 0:
                        back.add(i)
                elif v not in state:
                    state[v] = 1
                    stack.append((v, iter(adj[v])))
                    break
            else:
                state[node] = 2
                stack.pop()
    return back


def _longest(nodes: list[str], edges, fwd: list[int], rev: set[int]) -> dict[str, int]:
    """Longest-path layer per node over the acyclic edge set (reversed edges flipped)."""
    succ: dict[str, list[str]] = {n: [] for n in nodes}
    indeg = {n: 0 for n in nodes}
    for i in [*fwd, *rev]:
        u, v = (edges[i][1], edges[i][0]) if i in rev else (edges[i][0], edges[i][1])
        if u in succ and v in succ:
            succ[u].append(v)
            indeg[v] += 1
    layer = {n: 0 for n in nodes}
    ready = [n for n in nodes if indeg[n] == 0]
    while ready:
        n = ready.pop(0)
        for v in succ[n]:
            layer[v] = max(layer[v], layer[n] + 1)
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
    return layer


def place(
    sc: Scene,
    cyc: str = "dfs",
    lane: str | None = None,
    cols: str = "longest",
    wrap: float | None = None,
) -> Layout:
    lay = Layout()
    edges = _edges(sc)
    ctl = _lane_nodes(sc, edges, lane)
    inputs = [p for p in sc.pins if sc.ports[p].direction == "input"]
    outputs = [p for p in sc.pins if sc.ports[p].direction == "output"]
    body = [n for n in sc.leaves if n not in ctl]
    live = [e for e in edges if e[0] not in ctl and e[1] not in ctl]
    linked = {m for e in live for m in e[:2]}
    to_ctl = {m for e in edges if e[0] in ctl or e[1] in ctl for m in e[:2]}

    def pin_rank(p: str) -> int:
        return 1 if p in linked else (0 if p in to_ctl else 2)

    inputs.sort(key=pin_rank)
    outputs.sort(key=pin_rank)
    order_nodes = [*inputs, *body, *outputs]
    rev = _break_cycles(sc, order_nodes, live, cyc)
    fwd = [i for i in range(len(live)) if i not in rev]

    # --- layers ---
    if cols == "hints":
        known = {b: c for b in body if (c := _hint_col(sc, b)) is not None}
        if not known:
            raise ValueError("no stage hints for this input")
        sub = {b: 0 for b in known}  # depth inside the stage column
        for _ in range(len(known)):
            changed = False
            for i in fwd:
                u, v = live[i][0], live[i][1]
                if u in known and v in known and known[u] == known[v] and sub[v] < sub[u] + 1:
                    sub[v], changed = sub[u] + 1, True
            if not changed:
                break
        used = sorted({(c, sub[b]) for b, c in known.items()})
        layer = {b: used.index((c, sub[b])) for b, c in known.items()}
        rest = [b for b in body if b not in layer]
        for _ in range(len(rest) + 1):  # unhinted blocks sit next to their neighbours
            for b in rest:
                preds = [layer[e[0]] for e in live if e[1] == b and e[0] in layer]
                succs = [layer[e[1]] for e in live if e[0] == b and e[1] in layer]
                if b not in layer and (preds or succs):
                    layer[b] = max(preds) + 1 if preds else max(0, min(succs) - 1)
        for b in rest:
            layer.setdefault(b, 0)
        rev = {i for i, e in enumerate(live) if layer.get(e[0], -1) > layer.get(e[1], 10**6)}
    else:
        layer = _longest(body, live, fwd, rev)
        for b in body:  # sources with no inputs move next to their first consumer
            succs = [layer[live[i][1]] for i in fwd if live[i][0] == b and live[i][1] in layer]
            fed = any(live[i][1] == b for i in fwd) or any(live[i][0] == b for i in rev)
            if succs and not fed:
                layer[b] = max(layer[b], min(succs) - 1)
    last = max(layer.values(), default=-1) + 2
    layer = {b: v + 1 for b, v in layer.items()}
    layer.update({p: 0 for p in inputs})
    layer.update({p: last for p in outputs})

    # --- dummies for edges that span more than one layer, shared per net ---
    members: list[list[str]] = [[] for _ in range(last + 1)]
    for n in order_nodes:
        members[layer[n]].append(n)
    links: list[tuple[str, str, float, float, bool]] = []  # left, right, frac, frac, is data
    height: dict[str, int] = {n: sc.size[n][1] for n in order_nodes}
    dummy_net: dict[str, str] = {}

    def frac(pid: str, node: str) -> float:
        return sc.poff[pid][1] / max(1, sc.size[node][1]) if pid in sc.poff else 0.5

    for u, v, net, cls, sp, tp in live:
        prio = cls not in NON_DATA
        a, b_ = (u, v) if layer[u] <= layer[v] else (v, u)
        fa = frac(sp if a == u else tp, a)
        fb = frac(tp if a == u else sp, b_)
        prev, pf = a, fa
        for ly in range(layer[a] + 1, layer[b_]):
            dn = f"~{net}~{ly}"
            if dn not in height:
                height[dn] = 0
                layer[dn] = ly
                dummy_net[dn] = net
                members[ly].append(dn)
            links.append((prev, dn, pf, 0.5, prio))
            prev, pf = dn, 0.5
        if layer[a] != layer[b_]:
            links.append((prev, b_, pf, fb, prio))
    links = list(dict.fromkeys(links))

    left: dict[str, list[tuple[str, float, float, bool]]] = {}
    right: dict[str, list[tuple[str, float, float, bool]]] = {}
    for a, b_, fa, fb, prio in links:
        right.setdefault(a, []).append((b_, fa, fb, prio))
        left.setdefault(b_, []).append((a, fb, fa, prio))

    # --- ordering: barycentre sweeps, siblings kept together ---
    def chain(n: str) -> tuple[str, ...]:
        return tuple(sc.chain(n)) if n in sc.blocks else ()

    def sweep(ly: int, nb: dict[str, list[tuple[str, float, float, bool]]]) -> None:
        idx = {n: i for row in members for i, n in enumerate(row)}
        bary = {}
        for n in members[ly]:
            vals = [idx[m] + f_other for m, _f, f_other, _p in nb.get(n, [])]
            bary[n] = sum(vals) / len(vals) if vals else float(idx[n])
        groups: dict[tuple[str, ...], list[float]] = {}
        for n in members[ly]:
            c = chain(n)
            for k in range(1, len(c) + 1):
                groups.setdefault(c[:k], []).append(bary[n])
        gm = {g: sum(v) / len(v) for g, v in groups.items()}

        def key(n: str):
            c = chain(n)
            return (*[(gm[c[:k]], c[k - 1]) for k in range(1, len(c) + 1)], (bary[n], ""))

        members[ly].sort(key=lambda n: [(a, b_) for a, b_ in key(n)])

    def crossings() -> int:
        idx = {n: i for row in members for i, n in enumerate(row)}
        total = 0
        per: dict[int, list[tuple[float, float]]] = {}
        for a, b_, fa, fb, _p in links:
            per.setdefault(layer[a], []).append((idx[a] + fa, idx[b_] + fb))
        for seg in per.values():
            seg.sort()
            for i in range(len(seg)):
                for j in range(i + 1, len(seg)):
                    if seg[i][0] < seg[j][0] and seg[i][1] > seg[j][1]:
                        total += 1
        return total

    best, best_x = [row[:] for row in members], crossings()
    for _ in range(6):
        for ly in range(1, last + 1):
            sweep(ly, left)
        for ly in range(last - 1, -1, -1):
            sweep(ly, right)
        x = crossings()
        if x < best_x:
            best, best_x = [row[:] for row in members], x
    members = best

    # --- y: align each node with what feeds it, keeping the order ---
    def gap(a: str, b_: str) -> int:
        """Dummies (height 0) are wire slots: 2 clear of a block, 1 clear of each other."""
        if height[a] and height[b_]:
            extra = 3 if a in sc.blocks and b_ in sc.blocks and chain(a) != chain(b_) else 0
            return GAP + extra
        return 2 if height[a] or height[b_] else 1

    y: dict[str, float] = {}
    for row in members:
        cur = 0
        for i, n in enumerate(row):
            if i:
                cur += gap(row[i - 1], n)
            y[n] = cur
            cur += height[n]

    def port_y(n: str, f: float) -> float:
        return y[n] + f * height[n]

    def align(ly: int, nb) -> None:
        bottom = None
        prev = None
        for n in members[ly]:
            nbs = nb.get(n, [])
            nbs = [x for x in nbs if x[3]] or nbs
            want = [port_y(m, fo) - f * height[n] for m, f, fo, _p in nbs]
            target = round(median(want)) if want else y[n]
            if bottom is not None:
                target = max(target, bottom + gap(prev, n))
            y[n] = target
            bottom, prev = target + height[n], n

    for _ in range(2):
        for ly in range(1, last + 1):
            align(ly, left)
        for ly in range(last - 1, -1, -1):
            align(ly, right)
    for ly in range(1, last + 1):
        align(ly, left)

    # --- x: one column per layer, channel width follows the number of nets in it ---
    widths = [max((sc.size[n][0] for n in row if n in sc.size), default=0) for row in members]
    nets_in: list[set[str]] = [set() for _ in range(last + 1)]
    for a, _b, _fa, _fb, _p in links:
        nets_in[layer[a]].add(dummy_net.get(a, a))
    xs, cur = [], 0
    for ly in range(last + 1):
        xs.append(cur)
        cur += widths[ly] + 7 + min(40, len(nets_in[ly]))

    # --- wrap layers into rows for a target aspect ratio ---
    row_of = [0] * (last + 1)
    if wrap and last >= 3:
        total_h = max((y[n] + height[n] for n in y), default=1) - min(y.values(), default=0)
        best_r, best_err = 1, abs(cur / max(1, total_h) - wrap)
        for r in range(2, 7):
            err = abs((cur / r) / max(1, (total_h + 10) * r) - wrap)
            if err < best_err:
                best_r, best_err = r, err
        per_row = cur / best_r
        for ly in range(last + 1):
            row_of[ly] = min(best_r - 1, int((xs[ly] + widths[ly] / 2) / per_row))
        row_h = max(1, total_h) + 10 + min(12, len(sc.wires) // 3)
        y0 = min(y.values(), default=0)
        starts = {r: min(xs[ly] for ly in range(last + 1) if row_of[ly] == r)
                  for r in set(row_of)}
        for n in y:
            y[n] += row_of[layer[n]] * row_h - y0
        xs = [xs[ly] - starts[row_of[ly]] for ly in range(last + 1)]

    for n in order_nodes:
        ly = layer[n]
        lay.pos[n] = (xs[ly] + (widths[ly] - sc.size[n][0]) // 2, int(y[n]))

    # --- control lane: a row above everything, each block over the middle of its sinks ---
    loose = [p for p in sc.pins if p not in linked]
    if ctl:
        top = min((lay.pos[n][1] for n in order_nodes if n not in loose), default=0)
        row_h = max(sc.size[c][1] for c in ctl)
        n_ctl = len({e[2] for e in edges if e[0] in ctl or e[1] in ctl})
        base = top - row_h - 5 - min(16, n_ctl)
        want = []
        for c in ctl:
            xsn = [lay.pos[m][0] for e in edges if c in e[:2] for m in e[:2] if m in lay.pos]
            want.append((sum(xsn) / len(xsn) if xsn else 0, c))
        cur_x = None
        for wx, c in sorted(want):
            x = int(wx - sc.size[c][0] / 2)
            x = x if cur_x is None else max(x, cur_x + 4)
            lay.pos[c] = (x, base + row_h - sc.size[c][1])
            cur_x = x + sc.size[c][0]
        for i, p in enumerate(q for q in loose if q in to_ctl):  # control pins join the lane
            lay.pos[p] = (lay.pos[p][0], base + 4 * i)
    low = max((lay.pos[n][1] + sc.size[n][1] for n in order_nodes if n not in loose), default=0)
    for i, p in enumerate(q for q in loose if q not in to_ctl):  # unconnected pins: bottom
        lay.pos[p] = (lay.pos[p][0], low + 3 + 4 * i)

    for b in sc.leaves:  # anything not reached (isolated blocks inside ctl logic etc.)
        lay.pos.setdefault(b, (0, 0))
    finish_placement(sc, lay)
    return lay


PLACERS = {
    "lay": dict(cyc="dfs"),
    "lay_ctl": dict(cyc="class", lane="infer"),
    "grid": dict(cyc="hints", lane="hints", cols="hints"),
    "lay_wrap": dict(cyc="dfs", wrap=16 / 9),
    "lay_ctl_wrap": dict(cyc="class", lane="infer", wrap=16 / 9),
    "grid_wrap": dict(cyc="hints", lane="hints", cols="hints", wrap=16 / 9),
}
