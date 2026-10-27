"""One place that puts e1 (and, through it, e0) on sys.path and re-exports what e2 reuses.

e2 is the third consumer of e1's model / render / metrics / route (after e1 itself and
pipeline/experiments/x1_l1_to_l3/draw_l3.py). That is the signal, per bootstrap §8, to
promote those modules to src/ once the format is a contract; until then they are shared by
path, so that e2's numbers stay comparable with e1's.

Module names in e2 must not collide with e1's (model, place, route, ext, metrics, render,
report, run) or e0's (spec, gen, real, topo, variants, fetch, run) or the stdlib (array).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
E1 = HERE.parent / "e1_layout_matrix"
E0 = HERE.parent / "e0_reference_inputs"
ROOT = HERE.parents[3]
RUNS = ROOT / "runs" / "e2_class_engines"
E0_INPUTS = ROOT / "runs" / "e0_reference_inputs" / "inputs"

for _p in (E0, E1):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ext  # noqa: E402
import spec  # noqa: E402
from metrics import measure, score  # noqa: E402
from model import (  # noqa: E402
    GLOBAL,
    NON_DATA,
    Layout,
    Rect,
    Scene,
    U,
    finish_placement,
    norm,
    short,
    text_units,
)
from render import render, roundtrip  # noqa: E402
from route import ROUTERS, route_astar  # noqa: E402

__all__ = [
    "GLOBAL", "NON_DATA", "U", "E0_INPUTS", "RUNS", "ROOT", "Layout", "Rect", "Scene", "ext",
    "finish_placement", "measure", "norm", "relocate_port", "render", "resize", "roundtrip",
    "route_astar", "ROUTERS", "score", "short", "spec", "text_units",
]

SIDE_ORDER = ("W", "E", "N", "S")


def ports_of(sc: Scene, bid: str) -> list[str]:
    return [pid for pid, n in sc.node_of.items() if n == bid]


def resize(sc: Scene, bid: str, w: int, h: int) -> None:
    """Give a node a new size. Ports keep their offset along their side (E ports move with
    the right edge, S ports with the bottom edge). Never smaller than the ports need."""
    need_w = need_h = 0
    for pid in ports_of(sc, bid):
        dx, dy = sc.poff[pid]
        if sc.side[pid] in "NS":
            need_w = max(need_w, dx + 1)
        else:
            need_h = max(need_h, dy + 1)
    w, h = max(int(w), need_w, 4), max(int(h), need_h, 3)
    sc.size[bid] = (w, h)
    for pid in ports_of(sc, bid):
        dx, dy = sc.poff[pid]
        s = sc.side[pid]
        sc.poff[pid] = {"W": (0, dy), "E": (w, dy), "N": (dx, 0), "S": (dx, h)}[s]


def relocate_port(sc: Scene, pid: str, side: str, at: int | None = None) -> None:
    """Move a port to another side of its node at offset `at` (None: next free slot).
    The node grows when the side gets crowded."""
    bid = sc.node_of[pid]
    w, h = sc.size[bid]
    others = [p for p in ports_of(sc, bid) if p != pid and sc.side[p] == side]
    taken = {sc.poff[p][0] if side in "NS" else sc.poff[p][1] for p in others}
    if at is None:
        at = 2
        while at in taken:
            at += 2
    sc.side[pid] = side
    if side in "NS":
        w = max(w, at + 2)
    else:
        h = max(h, at + 2)
    sc.size[bid] = (w, h)
    sc.poff[pid] = {"W": (0, at), "E": (w, at), "N": (at, 0), "S": (at, h)}[side]
    resize(sc, bid, w, h)
