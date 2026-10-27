"""x4 FSM checks on FsmGraph v0.1: G2 structural and G5 style independence (isomorphism).

    uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/fsm_check.py \
        orig=runs/.../orig.json S1=runs/.../S1.json S2=runs/.../S2.json

G2 (`structural`): fsm_spec.validate (unique ids, known src/dst, exactly one reset state, one
transition per pair) plus the e4 `check_fsm.py` rules (transitions present, no '*' / ANY_STATE
state); states unreachable from reset over the drawn edges are warnings, not issues (they are
drawn with the `unreached` style).
G5 (`isomorphic`): networkx isomorphism of the variants' graphs, nodes matched on the reset flag,
edges compared with multiplicity (MultiDiGraph), so bridge expansions/merges are covered.
Self-loops are excluded from the gate graph (`pairs`) because syntactic extraction lists only
the self-loops written in the RTL while execution sees every hold; the strict variant with
self-loops is reported as `pairs_with_self_loops`.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
from pathlib import Path

import networkx as nx

_HERE = Path(__file__).resolve().parent


def _sibling(name: str):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


x4_tools = _sibling("x4_tools")
fsm_spec = x4_tools.x4("fsm_spec")


def _reach(g) -> set[str]:
    reset = [s.id for s in g.states if s.reset]
    seen, todo = set(reset), list(reset)
    while todo:
        s = todo.pop()
        for t in g.transitions:
            if t.src == s and t.dst not in seen:
                seen.add(t.dst)
                todo.append(t.dst)
    return seen


def structural(g) -> dict:
    """G2: {ok, issues[], warnings[]}; never raises."""
    issues = list(fsm_spec.validate(g))
    if not g.transitions:
        issues.append("no transitions")
    bad = [s.name for s in g.states if s.name in ("*", "ANY_STATE")]
    if bad:
        issues.append(f"wildcard state node {bad}")
    warnings = []
    if any(s.reset for s in g.states):
        unreach = sorted(s.name for s in g.states if s.id not in _reach(g))
        if unreach:
            warnings.append(f"unreachable from reset over drawn edges: {unreach}")
    not_reached = sorted(s.name for s in g.states if not s.reached)
    if not_reached:
        warnings.append(f"not reached by execution: {not_reached}")
    vals = [s.value for s in g.states if s.value is not None]
    if len(set(vals)) != len(vals):
        warnings.append("two states share an encoded value")
    if any(s.value is None for s in g.states):
        warnings.append("state value unknown for " +
                        str(sorted(s.name for s in g.states if s.value is None)))
    return {"ok": not issues, "issues": issues, "warnings": warnings}


def to_nx(g, self_loops: bool = False) -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    for s in g.states:
        G.add_node(s.id, reset=bool(s.reset))
    for t in g.transitions:
        if self_loops or t.src != t.dst:
            G.add_edge(t.src, t.dst)
    return G


def _iso(a, b, self_loops: bool) -> bool:
    return nx.is_isomorphic(
        to_nx(a, self_loops), to_nx(b, self_loops),
        node_match=lambda x, y: x["reset"] == y["reset"],
        edge_match=lambda x, y: len(x) == len(y),  # multiplicity of parallel edges
    )


def isomorphic(graphs: dict) -> dict:
    """G5 across variants {name: FsmGraph}: {ok, pairs{"a~b": bool}, pairs_with_self_loops,
    sizes{name: [states, edges, self_loops]}}. ok is None (not applicable, with `reason`) when
    there are fewer than two variants."""
    names = list(graphs)
    pairs, strict = {}, {}
    for a, b in itertools.combinations(names, 2):
        pairs[f"{a}~{b}"] = _iso(graphs[a], graphs[b], False)
        strict[f"{a}~{b}"] = _iso(graphs[a], graphs[b], True)
    sizes = {n: [len(g.states), sum(t.src != t.dst for t in g.transitions),
                 sum(t.src == t.dst for t in g.transitions)] for n, g in graphs.items()}
    out = {"ok": all(pairs.values()) if pairs else None, "pairs": pairs,
           "pairs_with_self_loops": strict, "sizes": sizes, "self_loops": "excluded"}
    if not pairs:
        out["reason"] = "n/a: fewer than two variants"
    return out


def main(argv: list[str]) -> int:
    graphs = {}
    for arg in argv:
        name, _, path = arg.partition("=")
        graphs[name] = fsm_spec.FsmGraph.model_validate_json(Path(path).read_text())
    for n, g in graphs.items():
        print(n, json.dumps(structural(g)))
    print(json.dumps(isomorphic(graphs), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
