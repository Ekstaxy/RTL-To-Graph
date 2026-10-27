"""Per-container diagram class from six indicators computed on the spec (memo §1.3).

Classes: A primitive schematic, B module datapath, C subsystem block diagram, D SoC overview
(hub / bus bars), E regular array. Classification is per container ("" is the root), never
once per drawing. Thresholds are the memo's initial guesses, kept as module constants so
X4 can report how they fare against the hand-assigned `expected` class in each sidecar.

    uv run --package rtl2d-l3 python layers/l3_draw/experiments/e2_class_engines/classify.py --table
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter

from e1lib import GLOBAL, NON_DATA, RUNS, norm, spec

PRIM = {"mux", "register", "pipeline_reg", "adder", "comparator", "gate", "alu", "fifo",
        "counter", "shifter", "mac", "regfile"}
CELL = PRIM | {"comb"}  # what a primitive-level schematic is made of
HUB_ROLES = {"bus", "crossbar", "noc"}
HUB_KINDS = {"bus", "crossbar", "noc", "interconnect"}
T = {"prim_A": 0.5, "n_A": 40, "prim_B": 0.15, "hub_D": 6, "n_D": 25, "n_fold": 60}
CLASSES = "ABCDE"


def levels(d: spec.Diagram) -> dict[str, list[str]]:
    """container id ("" = root) -> direct children (leaves and containers)."""
    out: dict[str, list[str]] = {"": []}
    for b in d.blocks:
        out.setdefault(b.parent_id or "", []).append(b.id)
    return out


def _parent(d: spec.Diagram) -> dict[str, str]:
    return {b.id: (b.parent_id or "") for b in d.blocks}


def child_at(parent: dict[str, str], level: str, bid: str | None) -> str | None:
    """The direct child of `level` that contains `bid`, or None if `bid` is outside."""
    cur = bid
    while cur is not None and cur != "":
        if parent.get(cur, "") == level:
            return cur
        cur = parent.get(cur, "")
        if cur == "" and level != "":
            return None
    return None


def level_edges(d: spec.Diagram, level: str, skip=GLOBAL) -> list[tuple[str, str, str]]:
    """(u, v, net id) pairs between direct children of `level`; nets of class `skip` excluded."""
    parent = _parent(d)
    owner = {p.id: p.owner_block_id for p in d.ports}
    pairs = []
    for n in d.nets:
        if norm(n.class_) in skip:
            continue
        u = child_at(parent, level, owner.get(n.source))
        for t in n.targets:
            v = child_at(parent, level, owner.get(t))
            if u and v and u != v:
                pairs.append((u, v, n.id))
    return pairs


def _sig(d: spec.Diagram, bid: str) -> tuple:
    b = next(x for x in d.blocks if x.id == bid)
    pn = tuple(sorted({re.sub(r"\d+", "#", p.id.rsplit(".", 1)[-1])
                       for p in d.ports if p.owner_block_id == bid}))
    return (norm(b.kind), re.sub(r"[\d#]+", "#", b.label), pn)


def indicators(d: spec.Diagram, side: dict, level: str) -> dict:
    lv = levels(d)
    kids = lv.get(level, [])
    containers = {k for k in kids if k in lv}
    leaves = [k for k in kids if k not in containers]
    kinds = {b.id: norm(b.kind) for b in d.blocks}
    nodes = side.get("nodes", {})

    pairs = level_edges(d, level)
    deg: dict[str, set[str]] = {k: set() for k in kids}
    for u, v, _n in pairs:
        deg[u].add(v)
        deg[v].add(u)
    # hub degree on data / bus nets only: a controller fanning `en` out to every register
    # is not a bus (calibration finding, README X4)
    deg_data: dict[str, set[str]] = {k: set() for k in kids}
    for u, v, _n in level_edges(d, level, NON_DATA):
        deg_data[u].add(v)
        deg_data[v].add(u)

    # replication: sidecar arrays fully inside this level, replicate tags, and groups of
    # leaves with the same kind, label pattern, port names AND the same neighbours outside
    # the group (interchangeable units: the "x8 peripherals" of a bus, not a random DAG).
    arrays = [a for a in side.get("arrays", [])
              if all(m in kids for row in a["members"] for m in row)]
    array_members = {m for a in arrays for row in a["members"] for m in row}
    by_sig: dict[tuple, list[str]] = {}
    for k in leaves:
        if k not in array_members:
            by_sig.setdefault(_sig(d, k), []).append(k)
    struct: list[list[str]] = []
    for g in by_sig.values():
        if len(g) < 3:
            continue
        by_nb: dict[tuple, list[str]] = {}
        for k in g:  # interchangeable = the same neighbours, inside and outside the group
            by_nb.setdefault(tuple(sorted(deg[k])), []).append(k)
        struct += [m for m in by_nb.values() if len(m) >= 3]
    tagged = [k for k in kids if "replicate" in nodes.get(k, {})]
    rep_groups = len(arrays) + len(struct) + len(tagged)
    covered = array_members | {m for g in struct for m in g}
    all_array = len(kids) >= 4 and covered == set(kids)

    n_vis = len(kids) - sum(len(g) - 1 for g in struct) - sum(
        sum(len(r) for r in a["members"]) - 1 for a in arrays if a["members"])
    prim = sum(1 for k in leaves if kinds[k] in PRIM)
    cells = sum(1 for k in leaves if kinds[k] in CELL)
    prim_ratio = prim / len(kids) if kids else 0.0

    def depth(c: str) -> int:
        return 1 + max((depth(x) for x in lv.get(c, []) if x in lv), default=0)
    dep = max((depth(c) for c in containers), default=0)

    hub_max = max((len(s) for s in deg_data.values()), default=0)
    hub_id = max(deg_data, key=lambda k: len(deg_data[k])) if deg_data else None
    roles = [k for k in kids if nodes.get(k, {}).get("role") in HUB_ROLES or kinds[k] in HUB_KINDS]
    distinct = {(u, v) for u, v, _n in pairs}
    return {
        "n_vis": n_vis, "prim_ratio": round(prim_ratio, 2), "depth": dep, "hub_max": hub_max,
        "hub": roles[0] if roles else hub_id, "roles": roles, "rep_groups": rep_groups,
        "edge_density": round(len(distinct) / n_vis, 2) if n_vis else 0.0,
        "all_array": all_array, "n_children": len(kids), "n_containers": len(containers),
        "cell_ratio": round(cells / len(kids), 2) if kids else 0.0,
        "groups": struct, "arrays": arrays,
    }


def classify_memo(ind: dict, side: dict, level: str) -> tuple[str, str]:
    """The memo's §1.3 decision list, verbatim."""
    forced = side.get("nodes", {}).get(level, {}).get("view_level")
    if forced is not None and forced in CLASSES:
        return forced, "sidecar view_level"
    if ind["all_array"]:
        return "E", "all children form one array"
    if ind["prim_ratio"] >= T["prim_A"] and ind["depth"] <= 1:
        if ind["n_vis"] <= T["n_A"]:
            return "A", f"prim_ratio {ind['prim_ratio']} >= {T['prim_A']}, depth <= 1"
        return "A", f"prim schematic, n_vis {ind['n_vis']} > {T['n_A']}: fold or split cones"
    if ind["prim_ratio"] >= T["prim_B"]:
        return "B", f"prim_ratio {ind['prim_ratio']} >= {T['prim_B']}"
    if ind["roles"]:
        return "D", f"hub role on {ind['roles'][0]}"
    if ind["hub_max"] >= T["hub_D"] or ind["n_vis"] > T["n_D"]:
        return "D", f"hub_max {ind['hub_max']} >= {T['hub_D']} or n_vis {ind['n_vis']} > {T['n_D']}"
    return "C", "default"


def classify_cal(ind: dict, side: dict, level: str) -> tuple[str, str]:
    """Calibrated on the X4 table (README): hubs are decided before primitives, and A means
    "nothing but cells" rather than "half primitives"."""
    forced = side.get("nodes", {}).get(level, {}).get("view_level")
    if forced is not None and forced in CLASSES:
        return forced, "sidecar view_level"
    if ind["all_array"]:
        return "E", "all children form one array"
    if ind["roles"]:
        return "D", f"hub role on {ind['roles'][0]}"
    if ind["n_containers"] == 0 and ind["n_children"] >= 5 and ind["cell_ratio"] >= 0.99:
        big = f"; n_vis {ind['n_vis']} > {T['n_A']}: fold or split cones"
        return "A", "only cells, no containers" + (big if ind["n_vis"] > T["n_A"] else "")
    if ind["n_children"] >= 4 and ind["hub_max"] >= T["hub_D"]:
        return "D", f"hub_max {ind['hub_max']} >= {T['hub_D']}"
    if ind["n_vis"] > T["n_D"]:
        return "D", f"n_vis {ind['n_vis']} > {T['n_D']}"
    if ind["prim_ratio"] >= T["prim_B"]:
        return "B", f"prim_ratio {ind['prim_ratio']} >= {T['prim_B']}"
    return "C", "default"


RULES = {"memo": classify_memo, "cal": classify_cal}
ENGINE_CLASS = {"A": "AB", "B": "AB", "C": "C", "D": "D", "E": "E"}


def classify(d: spec.Diagram, side: dict, rules: str = "cal") -> dict[str, dict]:
    out = {}
    for level in levels(d):
        ind = indicators(d, side, level)
        cls, why = RULES[rules](ind, side, level)
        out[level] = {"class": cls, "why": why, "ind": ind,
                      "fold": ind["n_vis"] > T["n_fold"]}
    return out


def table(names: list[str]) -> str:
    import inputs

    rows = ["| input | level | n_vis | prim | cells | depth | hub_max | rep | dens | memo | cal "
            "| expected | |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    conf: dict[str, Counter] = {"memo": Counter(), "cal": Counter()}
    for name in names:
        d, _h, s = inputs.load(name)
        res = {k: classify(d, s, k) for k in RULES}
        for level in res["cal"]:
            exp = s.get("expected", {}).get(level, "?")
            i = res["cal"][level]["ind"]
            pm, pc = res["memo"][level]["class"], res["cal"][level]["class"]
            conf["memo"][(exp, pm)] += 1
            conf["cal"][(exp, pc)] += 1
            mark = "ok" if exp == pc else ("**miss**" if exp != "?" else "")
            rows.append(f"| {name} | {level or '(root)'} | {i['n_vis']} | {i['prim_ratio']} "
                        f"| {i['cell_ratio']} | {i['depth']} | {i['hub_max']} | {i['rep_groups']} "
                        f"| {i['edge_density']} | {pm} | {pc} | {exp} | {mark} |")
    for k in RULES:
        rows.append("")
        rows.append(f"Confusion for the `{k}` rules (rows expected, columns predicted):")
        rows.append("")
        rows.append("| expected \\ predicted | " + " | ".join(CLASSES) + " |")
        rows.append("|---|" + "---|" * len(CLASSES))
        for e in CLASSES:
            rows.append(f"| {e} | " + " | ".join(str(conf[k][(e, p)]) for p in CLASSES) + " |")
        total = sum(conf[k].values())
        hit = sum(v for (e, p), v in conf[k].items() if e == p)
        same_engine = sum(v for (e, p), v in conf[k].items()
                          if e != "?" and ENGINE_CLASS.get(e) == ENGINE_CLASS.get(p))
        rows.append(f"\n`{k}`: {hit} of {total} levels match the hand-assigned class; "
                    f"{same_engine} of {total} land on the same engine "
                    f"(A and B share one). Thresholds {json.dumps(T)}.")
    return "\n".join(rows)


if __name__ == "__main__":
    import inputs

    names = [p.stem.replace(".diagram", "")
             for p in sorted((RUNS / "inputs").glob("*.diagram.json"))]
    if "--table" in sys.argv:
        md = table(names)
        (RUNS / "classify.md").write_text(md)
        print(md)
    else:
        for name in names:
            d, _h, s = inputs.load(name)
            print(name, {k: v["class"] for k, v in classify(d, s).items()})
