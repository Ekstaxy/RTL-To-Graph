"""D-class level engine: hubs become bars, everything else sits in rows along them.

The memo's "bus bar" transform (§4.4): the hub (sidecar role bus / crossbar / noc, else
the node with the largest data degree) is drawn as a bar spanning its container; the
items that talk to it are packed in a row above and a row below with equalised cells;
their hub ports move to the bar-facing side and the bar's ports sit right across, so
each attachment is a short vertical stub. Items with no hub edge go in a top row (pins:
inputs left, outputs right). Several hubs stack, each with its own two rows. Topology is
expressed by *where* a box sits; only non-hub nets are long wires (routed globally by A*).

`place_grid` is the same packing without a bar (the control for X1: rows and columns
only), used for class D levels when `busbar` is not selected.
"""

from __future__ import annotations

from statistics import median

from compose import GAP, Item, Level
from e1lib import Scene, ports_of, relocate_port, resize

BAR_H = 3
ROW_GAP = GAP + 1  # bar to row: stub length


def _hubs(lv: Level, side: dict) -> list[str]:
    nodes = side.get("nodes", {})
    tagged = [i.id for i in lv.items
              if nodes.get(i.id, {}).get("role") in ("bus", "crossbar", "noc")]
    if tagged:
        return sorted(tagged, key=lambda i: -lv.item(i).deg)
    if lv.hub and lv.hub in {i.id for i in lv.items}:
        return [lv.hub]
    return []


def _cells(items: list[Item]) -> int:
    """Equalised cell width: the 75th percentile of the row's widths; wider items keep
    their own width."""
    ws = sorted(i.w for i in items)
    if not ws:
        return 0
    return int(ws[min(len(ws) - 1, (3 * len(ws)) // 4)])


def _lay_row(items: list[Item], x0: int, y: int, pos: dict, cell: int | None = None) -> int:
    """Place a row left to right; returns its right edge."""
    cw = cell if cell is not None else _cells(items)
    x = x0
    for it in items:
        w = max(cw, it.w)
        pos[it.id] = (x + (w - it.w) // 2, y)
        x += w + GAP
    return x - GAP


def place_level(sc: Scene, lv: Level, side: dict, **_kw) -> None:
    hubs = _hubs(lv, side)
    if not hubs:
        return place_grid(sc, lv, side)
    items = {i.id: i for i in lv.items}
    hubset = set(hubs)
    # which hub does each item talk to most?
    talk: dict[str, dict[str, int]] = {}
    hub_edges: list[tuple[str, str, str]] = []  # (device, hub, net)
    for u, v, nid, _c in lv.edges:
        for dev, hub in ((u, v), (v, u)):
            if hub in hubset and dev not in hubset:
                talk.setdefault(dev, {}).setdefault(hub, 0)
                talk[dev][hub] += 1
                hub_edges.append((dev, hub, nid))
    of_hub: dict[str, list[str]] = {h: [] for h in hubs}
    free: list[str] = []
    for it in lv.items:
        if it.id in hubset:
            continue
        if it.id in talk:
            best = max(talk[it.id], key=lambda h: (talk[it.id][h], -hubs.index(h)))
            of_hub[best].append(it.id)
        else:
            free.append(it.id)
    # rows: alternate above / below in model order, keep the busiest device first
    above: dict[str, list[str]] = {}
    below: dict[str, list[str]] = {}
    for h, devs in of_hub.items():
        if devs:  # the busiest device (the host) leads the top row; the rest keep model order
            host = max(devs, key=lambda d: items[d].deg)
            devs = [host] + [d for d in devs if d != host]
        wa = wb = 0
        above[h], below[h] = [], []
        for d in devs:
            if wa <= wb:
                above[h].append(d)
                wa += items[d].w + GAP
            else:
                below[h].append(d)
                wb += items[d].w + GAP
    # hub-facing ports: which device ports and which hub ports belong to each attachment
    owner = {p.id: p.owner_block_id for p in sc.ports.values()}
    nets = {n.id: n for n in sc.wires}
    dev_ports: dict[tuple[str, str], list[str]] = {}  # (device, hub) -> device ports
    hub_ports: dict[tuple[str, str], list[str]] = {}  # (device, hub) -> hub ports
    for dev, hub, nid in hub_edges:
        n = nets[nid]
        for pid in (n.source, *n.targets):
            o = owner.get(pid)
            if o == dev and items[dev].kind == "leaf":
                dev_ports.setdefault((dev, hub), []).append(pid)
            elif o == hub:
                hub_ports.setdefault((dev, hub), []).append(pid)
    for k in dev_ports:
        dev_ports[k] = list(dict.fromkeys(dev_ports[k]))
    for k in hub_ports:
        hub_ports[k] = list(dict.fromkeys(hub_ports[k]))

    def spread(center: int, k: int) -> int:
        """offsets around a centre: 0, -2, +2, -4, +4 ..."""
        return center + ((k + 1) // 2) * (2 if k % 2 else -2) if k else center

    # device ports to the bar-facing side, centred under the label
    for (dev, hub), ps in dev_ports.items():
        s = "S" if dev in above[hub] else "N"
        w = max(items[dev].w, 2 * len(ps) + 2)
        resize(sc, dev, w, items[dev].h)
        cx = sc.size[dev][0] // 2
        for k, pid in enumerate(ps):
            relocate_port(sc, pid, s, max(1, min(sc.size[dev][0] - 1, spread(cx, k))))
    # every hub port that faces a device goes N or S now, so the bar can be flat
    for (dev, hub), ps in hub_ports.items():
        s = "N" if dev in above[hub] else "S"
        for k, pid in enumerate(ps):
            relocate_port(sc, pid, s, 2 + 2 * k)
    for it in lv.items:  # sizes may have grown
        if it.kind == "leaf":
            it.w, it.h = sc.size[it.id]

    pos: dict[str, tuple[int, int]] = {}
    y = 0
    pins_in = [i.id for i in lv.items if i.kind == "pin" and sc.ports[i.id].direction == "input"]
    pins_out = [i.id for i in lv.items if i.kind == "pin" and sc.ports[i.id].direction == "output"]
    free = [f for f in free if f not in pins_in and f not in pins_out]
    x_left = max((items[p].w for p in pins_in), default=0) + GAP if pins_in else 0
    if free:
        _lay_row([items[f] for f in free], x_left, y, pos)
        y += max(items[f].h for f in free) + ROW_GAP
    bar_right = x_left
    for h in hubs:
        rows = [[items[d] for d in above[h]], [items[d] for d in below[h]]]
        cell = _cells([i for i in rows[0] + rows[1] if i.kind == "leaf"])
        top_h = max((i.h for i in rows[0]), default=0)
        right_a = _lay_row(rows[0], x_left, y, pos, cell) if rows[0] else x_left
        y_bar = y + top_h + (ROW_GAP if rows[0] else 0)
        y_below = y_bar + BAR_H + ROW_GAP
        right_b = _lay_row(rows[1], x_left, y_below, pos, cell) if rows[1] else x_left
        bar_w = max(right_a, right_b, x_left + 12) - x_left
        # bar ports right across from each device's ports, then the bar itself
        used: dict[str, set[int]] = {"N": set(), "S": set()}
        for (dev, hub), ps in hub_ports.items():
            if hub != h:
                continue
            s = "N" if dev in above[h] else "S"
            dps = dev_ports.get((dev, hub), [])
            for k, pid in enumerate(ps):
                if k < len(dps):  # straight stub: same x as the device port
                    at = pos[dev][0] + sc.poff[dps[k]][0] - x_left
                else:
                    at = pos[dev][0] + items[dev].w // 2 - x_left + 2 * k
                at = max(1, min(bar_w - 1, at))
                while at in used[s]:
                    at += 2
                used[s].add(at)
                relocate_port(sc, pid, s, at)
        # ports left on W/E (nets to other hubs, to other levels, or hidden) go onto the
        # bar faces too, alternating N/S at free slots, so the bar stays flat
        k = 0
        for pid in ports_of(sc, h):
            if sc.side[pid] in "WE":
                s = "N" if k % 2 == 0 else "S"
                at = 2
                while at in used[s]:
                    at += 2
                used[s].add(at)
                relocate_port(sc, pid, s, at)
                k += 1
        resize(sc, h, bar_w, BAR_H)
        pos[h] = (x_left, y_bar)
        items[h].w, items[h].h = sc.size[h]
        bar_right = max(bar_right, x_left + items[h].w)
        y = y_below + (max((i.h for i in rows[1]), default=0) + ROW_GAP if rows[1] else 0)
        y += GAP
    # pins: inputs down the left, outputs down the right
    yy = 0
    for p in pins_in:
        pos[p] = (0, yy)
        yy += items[p].h + 2
    yy = 0
    for p in pins_out:
        pos[p] = (bar_right + GAP + 2, yy)
        yy += items[p].h + 2
    lv.pos = pos
    lv.notes.append(f"busbar hubs {hubs}")


def place_grid(sc: Scene, lv: Level, side: dict, **_kw) -> None:
    """Rows of equalised cells, no bar: items in model order, wrapped towards 16:9."""
    items = [i for i in lv.items if i.kind != "pin"]
    pins_in = [i for i in lv.items if i.kind == "pin" and sc.ports[i.id].direction == "input"]
    pins_out = [i for i in lv.items if i.kind == "pin" and sc.ports[i.id].direction == "output"]
    pos: dict[str, tuple[int, int]] = {}
    if not items:
        lv.pos = pos
        return
    cell = _cells(items)
    total = sum(max(cell, i.w) + GAP for i in items)
    per_row = max(1, round((total * 0.56 / (median(i.h for i in items) + GAP)) ** 0.5))
    per_row = max(per_row, 1)
    x_left = max((i.w for i in pins_in), default=0) + GAP if pins_in else 0
    y, right = 0, x_left
    for r in range(0, len(items), per_row):
        row = items[r:r + per_row]
        right = max(right, _lay_row(row, x_left, y, pos, cell))
        y += max(i.h for i in row) + GAP
    yy = 0
    for p in pins_in:
        pos[p.id] = (0, yy)
        yy += p.h + 2
    yy = 0
    for p in pins_out:
        pos[p.id] = (right + GAP + 2, yy)
        yy += p.h + 2
    lv.pos = pos
