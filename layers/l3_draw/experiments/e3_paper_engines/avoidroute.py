"""Orthogonal, object-avoiding routing with libavoid for every engine's placement.

Each leaf, bar and terminal is an obstacle with exclusive connection pins on its sides
(bars only on their long sides, terminals on the side facing the drawing), so lines
leave a box at distinct points, as in the figures. Containers are not obstacles.
"""

from __future__ import annotations

import math

import p3lib
from grammar import PGraph
from layout import Place


def route(g: PGraph, pl: Place) -> dict[str, list[tuple[float, float]]]:
    deg: dict[str, int] = {}
    for e in g.edges:
        deg[e.a] = deg.get(e.a, 0) + 1
        deg[e.b] = deg.get(e.b, 0) + 1
    lines = []
    sid = {}
    for k, nid in enumerate(sorted(pl.pos)):
        n = g.nodes[nid]
        x, y = pl.pos[nid]
        s = f"s{k}"
        sid[nid] = s
        lines.append(f"S {s} {x:.2f} {y:.2f} {n.w:.2f} {n.h:.2f}")
        c = deg.get(nid, 0)
        if n.kind == "bar":
            lines.append(f"P {s} NS {max(2, c + 2)}")
        elif n.kind == "pin":
            mid = sum(p[0] for p in pl.pos.values()) / len(pl.pos)
            lines.append(f"P {s} {'E' if x < mid else 'W'} {max(2, c + 1)}")
        else:
            lines.append(f"P {s} NESW {max(2, math.ceil(c / 2) + 1)}")
    # container titles are obstacles too, so no line runs over a subsystem's name
    for k, (cid, (x, y, _w, _h)) in enumerate(sorted(pl.boxes.items())):
        tw = len(g.nodes[cid].label) * 7.2 + 14
        lines.append(f"S t{k} {x + 4:.2f} {y + 4:.2f} {tw:.2f} 20")
    for e in g.edges:
        lines.append(f"C {e.id} {sid[e.a]} {sid[e.b]}")
    exe = p3lib.need(p3lib.BIN / "avoid_run", "avoid_run")
    text = "\n".join(lines) + "\n"
    try:
        out = p3lib.run([exe, "10", "7", "0"], text, 300)
    except RuntimeError:
        # libavoid's nudging asserts on some inputs; the NDEBUG build skips the assertion
        nd = p3lib.need(p3lib.BIN / "avoid_run_nd", "avoid_run_nd")
        out = p3lib.run([nd, "10", "7", "0"], text, 300)
        pl.notes.append("libavoid assertion hit; NDEBUG build used")
    routes = {}
    for line in out.splitlines():
        f = line.split()
        if f and f[0] == "R":
            routes[f[1]] = [tuple(map(float, p.split(","))) for p in f[2:]]
    return routes
