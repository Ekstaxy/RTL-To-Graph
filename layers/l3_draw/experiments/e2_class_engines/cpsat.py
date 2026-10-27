"""X6: exact grid placement with OR-Tools CP-SAT, after Yoghourdjian et al. 2015.

One container level at a time (compose gives sizes for sub-containers). Items sit on an
integer grid of 2-unit cells, do not overlap (one free ring of GAP units), and the solver
minimises the weighted Manhattan length between connected items plus the bounding box.
Pins are pinned to the left (inputs) or right (outputs) column. A time limit returns the
best feasible solution found; `lv.notes` records objective, bound and status so the bench
can report how far from optimal the layout is.

Needs `--with ortools`; without it the engine raises ValueError (run.py records n/a).
"""

from __future__ import annotations

import time

from compose import GAP, Level
from e1lib import Scene

CELL = 2


def place_level(sc: Scene, lv: Level, side: dict, seconds: float = 30.0, **_kw) -> None:
    try:
        from ortools.sat.python import cp_model
    except ImportError as e:  # recorded as n/a by run.py
        raise ValueError("ortools not installed (run with --with ortools)") from e
    items = [i for i in lv.items]
    if not items:
        lv.pos = {}
        return
    n = len(items)
    span = sum(max(i.w, i.h) + GAP for i in items)  # loose upper bound in units
    gmax = max(2, span // CELL)
    m = cp_model.CpModel()
    gx = [m.NewIntVar(0, gmax, f"gx{k}") for k in range(n)]
    gy = [m.NewIntVar(0, gmax, f"gy{k}") for k in range(n)]
    x = [m.NewIntVar(0, gmax * CELL, f"x{k}") for k in range(n)]
    y = [m.NewIntVar(0, gmax * CELL, f"y{k}") for k in range(n)]
    for k in range(n):
        m.Add(x[k] == gx[k] * CELL)
        m.Add(y[k] == gy[k] * CELL)
    xi = [m.NewIntervalVar(x[k], items[k].w + GAP, m.NewIntVar(0, 10**6, f"xe{k}"), f"xi{k}")
          for k in range(n)]
    yi = [m.NewIntervalVar(y[k], items[k].h + GAP, m.NewIntVar(0, 10**6, f"ye{k}"), f"yi{k}")
          for k in range(n)]
    m.AddNoOverlap2D(xi, yi)
    idx = {it.id: k for k, it in enumerate(items)}
    W = m.NewIntVar(0, gmax * CELL + 200, "W")
    H = m.NewIntVar(0, gmax * CELL + 200, "H")
    for k, it in enumerate(items):
        m.Add(W >= x[k] + it.w)
        m.Add(H >= y[k] + it.h)
        if it.kind == "pin":
            if sc.ports[it.id].direction == "input":
                m.Add(x[k] == 0)
            else:  # within one grid cell of the right edge (widths differ in parity)
                m.Add(x[k] + it.w >= W - CELL)
    terms = []
    weight: dict[tuple[int, int], int] = {}
    for u, v, _nid, c in lv.edges:
        a, b = idx[u], idx[v]
        if a == b:
            continue
        key = (min(a, b), max(a, b))
        weight[key] = weight.get(key, 0) + (2 if c not in ("control", "status") else 1)
    for (a, b), wgt in weight.items():
        dx = m.NewIntVar(0, 10**6, f"dx{a}_{b}")
        dy = m.NewIntVar(0, 10**6, f"dy{a}_{b}")
        cxa = 2 * x[a] + items[a].w
        cxb = 2 * x[b] + items[b].w
        cya = 2 * y[a] + items[a].h
        cyb = 2 * y[b] + items[b].h
        m.AddAbsEquality(dx, cxa - cxb)
        m.AddAbsEquality(dy, cya - cyb)
        terms.append(wgt * (dx + dy))
    m.Minimize(sum(terms) + 2 * (W + H))
    # hint: a simple row packing so the solver starts feasible
    xx = yy = rh = 0
    per = max(1, int(n ** 0.5))
    for k, it in enumerate(items):
        if k and k % per == 0:
            xx, yy, rh = 0, yy + rh + GAP, 0
        m.AddHint(gx[k], xx // CELL)
        m.AddHint(gy[k], yy // CELL)
        xx += it.w + GAP + (CELL - (it.w + GAP) % CELL) % CELL
        rh = max(rh, it.h)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = 8
    t0 = time.perf_counter()
    st = solver.Solve(m)
    name = solver.StatusName(st)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"cpsat {name} after {seconds}s")
    lv.pos = {it.id: (solver.Value(x[k]), solver.Value(y[k])) for k, it in enumerate(items)}
    lv.notes.append(f"cpsat n={n} {name} obj={solver.ObjectiveValue():.0f} "
                    f"bound={solver.BestObjectiveBound():.0f} {time.perf_counter() - t0:.1f}s")
