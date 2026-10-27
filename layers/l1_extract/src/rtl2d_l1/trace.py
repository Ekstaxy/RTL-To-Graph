"""Trace engine (SPEC §6): anchors -> architecture-relevant region of the graph.

1. typed slicing from every anchor (direction / edge types chosen by its trace hint),
   bounded by register boundaries and depth;
2. seed-to-seed connection with a node-weighted Steiner approximation (Mehlhorn);
3. semantic closure (enables, mux selects, valid/ready pairing, resets).
"""

from __future__ import annotations

import heapq
import math
import re
from dataclasses import dataclass, field

import networkx as nx
from networkx.algorithms.approximation import steiner_tree

from .frontend.entities import EntityTable
from .frontend.graph import DesignGraph, EdgeType, Node
from .schema import ModuleResult
from .taxonomy import IMPORTANCE_VALUE, Level, TraceHint

_SLICE_TYPES = {
    TraceHint.control_backward: (
        {EdgeType.CONTROL, EdgeType.DATA, EdgeType.ADDR, EdgeType.PORT},
        "back",
    ),
    TraceHint.data_backward: ({EdgeType.DATA, EdgeType.ADDR, EdgeType.PORT}, "back"),
    TraceHint.forward: ({EdgeType.DATA, EdgeType.CONTROL, EdgeType.ADDR, EdgeType.PORT}, "fwd"),
    TraceHint.interface: ({EdgeType.DATA, EdgeType.CONTROL, EdgeType.ADDR, EdgeType.PORT}, "iface"),
}


# node cost for the Steiner step: prefer architecturally meaningful nodes
def node_cost(n: Node) -> float:
    if n.port_dir:
        return 0.1
    if n.depth is not None:
        return 0.3
    if n.is_state:
        return 0.2
    if n.local:
        return 1.2
    if n.driven_by & {"always_comb", "always"}:
        return 0.7
    return 1.0


@dataclass
class Region:
    nodes: dict[str, list[str]] = field(default_factory=dict)  # node key -> reasons
    total_nodes: int = 0
    scores: dict[str, float] = field(default_factory=dict)  # relevance score per node
    anchor_edges: list[dict] = field(default_factory=list)  # abstract anchor -> anchor connectivity

    def add(self, key: str, reason: str) -> bool:
        new = key not in self.nodes
        self.nodes.setdefault(key, [])
        if reason not in self.nodes[key]:
            self.nodes[key].append(reason)
        return new

    @property
    def reduction(self) -> float:
        return 1.0 - (len(self.nodes) / self.total_nodes) if self.total_nodes else 0.0

    def internal_reduction(self, G: DesignGraph) -> float:
        """Reduction over internal (non-port) nodes only: ports are pins of a block diagram and are
        always drawn, so they would otherwise dilute the metric for small modules."""
        internal = [k for k, n in G.nodes.items() if not n.port_dir]
        if not internal:
            return 0.0
        kept = sum(1 for k in internal if k in self.nodes)
        return 1.0 - kept / len(internal)

    def merge(self, other: Region) -> None:
        for k, rs in other.nodes.items():
            for r in rs:
                self.add(k, r)
        for k, v in other.scores.items():
            self.scores[k] = max(self.scores.get(k, 0.0), v)
        # anchor_edges are level-specific (finer anchors split coarse arrows):
        # the finer region's arrows win
        self.anchor_edges = list(other.anchor_edges)

    def edges(self, G: DesignGraph) -> list[tuple[str, str, str]]:
        keep = self.nodes
        return [
            (s, t, d["type"].value)
            for s, t, d in G.g.edges(data=True)
            if s in keep and t in keep and d["type"] not in (EdgeType.CLOCK,)
        ]

    def to_json(self, G: DesignGraph) -> dict:
        return {
            "total_nodes": self.total_nodes,
            "region_nodes": len(self.nodes),
            "reduction": round(self.reduction, 4),
            "internal_reduction": round(self.internal_reduction(G), 4),
            "nodes": {k: v for k, v in sorted(self.nodes.items())},
            "scores": {k: round(v, 3) for k, v in sorted(self.scores.items()) if k in self.nodes},
            "edges": [{"src": s, "dst": t, "type": ty} for s, t, ty in self.edges(G)],
            "anchor_edges": self.anchor_edges,
        }


# --------------------------------------------------------------- anchor mapping
def _rel_pattern(name: str) -> re.Pattern:
    return re.compile("^" + re.escape(name).replace(r"\[\*\]", r"\[\d+\]") + "$")


def entity_nodes(G: DesignGraph, table: EntityTable, entity_id: str) -> list[str]:
    """All graph nodes (in every instance of the module) that realize an entity."""
    row = table.by_id().get(entity_id)
    if row is None:
        return []
    if row.kind == "inst":
        return []
    pat = _rel_pattern(row.name)
    out = []
    for n in G.nodes.values():
        if n.module == table.module and pat.match(n.rel):
            out.append(n.key)
    return out


def anchor_seeds(
    G: DesignGraph, tables: dict[str, EntityTable], results: dict[str, ModuleResult]
) -> dict[str, dict]:
    seeds: dict[str, dict] = {}
    for mod, res in results.items():
        t = tables.get(mod)
        if t is None:
            continue
        for a in res.anchors:
            for k in entity_nodes(G, t, a.id):
                prev = seeds.get(k)
                w = IMPORTANCE_VALUE[a.importance] * a.confidence
                if prev is None or w > prev["weight"]:
                    seeds[k] = {
                        "module": mod,
                        "id": a.id,
                        "role": a.role.value,
                        "trace": a.trace,
                        "weight": w,
                    }
    return seeds


# ---------------------------------------------------------------------- slicing
_EDGE_BASE = {EdgeType.DATA: 1.0, EdgeType.CONTROL: 1.0, EdgeType.ADDR: 1.5, EdgeType.PORT: 0.0}
REG_CROSS_COST = 1.0  # extra cost to step onto a register (one clock stage away)


def _edge_cost(G: DesignGraph, explained: str, et: EdgeType) -> float:
    """Cost of explaining `explained` through one more `et` edge. Dilution: when a node has
    many predecessors of this type (e.g. 20 nested if-conditions in one big always block),
    each individual predecessor matters less."""
    base = _EDGE_BASE.get(et, 1.0)
    if et == EdgeType.PORT:
        return 0.0
    n_same = sum(1 for _, t in G.preds(explained, {et}))
    return base + 0.5 * math.log2(1 + max(0, n_same - 1))


def typed_slice(
    G: DesignGraph,
    start: str,
    hint: TraceHint,
    depth: float = 6.0,
    reg_hops: int = 1,
    stop_at: set[str] | None = None,
) -> dict[str, float]:
    """Cost-bounded typed slice (Dijkstra). Returns {node: cost from start}.

    - direction / edge types come from the trace hint;
    - PORT edges are free (hierarchy is transparent);
    - stepping onto a register costs REG_CROSS_COST and, after `reg_hops` registers, the
      register is included but not expanded;
    - nodes in `stop_at` (other anchors) are included but not expanded (they own their slice)."""
    stop_at = stop_at or set()
    if hint == TraceHint.none:
        return {start: 0.0}
    types, mode = _SLICE_TYPES[hint]
    n0 = G.nodes[start]
    if mode == "iface":
        mode = "fwd" if n0.port_dir == "in" else "back"
    best: dict[str, tuple[float, int]] = {start: (0.0, 0)}
    heap: list[tuple[float, int, str]] = [(0.0, 0, start)]
    while heap:
        c, regs, k = heapq.heappop(heap)
        if best.get(k, (math.inf, 0))[0] < c:
            continue
        if k != start and (k in stop_at or (G.nodes[k].is_state and regs >= reg_hops)):
            continue
        nbrs = G.preds(k, types) if mode == "back" else G.succs(k, types)
        for nb, et in nbrs:
            if nb == k:
                continue
            explained = k if mode == "back" else nb
            nn = G.nodes[nb]
            nc = c + _edge_cost(G, explained, et) + (REG_CROSS_COST if nn.is_state else 0.0)
            nr = regs + (1 if nn.is_state else 0)
            if nc > depth:
                continue
            if nc < best.get(nb, (math.inf, 0))[0]:
                best[nb] = (nc, nr)
                heapq.heappush(heap, (nc, nr, nb))
    return {k: v[0] for k, v in best.items()}


# ---------------------------------------------------------------------- steiner
def _undirected_weighted(G: DesignGraph) -> nx.Graph:
    U = nx.Graph()
    for k, _n in G.nodes.items():
        U.add_node(k)
    for s, t, d in G.g.edges(data=True):
        if s == t or d["type"] in (EdgeType.CLOCK, EdgeType.RESET):
            continue
        w = (node_cost(G.nodes[s]) + node_cost(G.nodes[t])) / 2.0
        if d["type"] == EdgeType.PORT:
            w *= 0.25
        if U.has_edge(s, t):
            w = min(w, U[s][t]["weight"])
        U.add_edge(s, t, weight=w)
    return U


def steiner_connect(G: DesignGraph, terminals: set[str]) -> set[str]:
    U = _undirected_weighted(G)
    out: set[str] = set()
    for comp in nx.connected_components(U):
        terms = [t for t in terminals if t in comp]
        if len(terms) < 2:
            continue
        sub = U.subgraph(comp)
        T = steiner_tree(sub, terms, weight="weight", method="mehlhorn")
        out |= set(T.nodes)
    return out


# ---------------------------------------------------------------------- closure
_PAIR = [("valid", "ready"), ("vld", "rdy"), ("req", "ack"), ("req", "gnt")]


def semantic_closure(G: DesignGraph, region: Region, control: bool = True) -> None:
    keys = [k for k, r in region.nodes.items() if "seed" in r]
    for k in keys:
        n = G.nodes[k]
        # enables / selects: narrow CONTROL predecessors, only when the anchor has few of them
        # (a register inside a giant nested if/case is explained by the scored slice instead)
        narrow = [
            p
            for p, _ in G.preds(k, {EdgeType.CONTROL})
            if p != k and G.nodes[p].width <= 4 and G.nodes[p].depth is None
        ]
        if control and len(narrow) <= 4:
            for p in narrow:
                region.add(p, "closure:control_of:" + n.name)
        if n.is_state:
            for p, _et in G.preds(k, {EdgeType.RESET}):
                region.add(p, "closure:reset")
    # handshake pairing within the same instance
    by_inst: dict[str, dict[str, str]] = {}
    for k, n in G.nodes.items():
        by_inst.setdefault(n.inst, {})[n.rel.lower()] = k
    for k in [k for k, r in region.nodes.items() if "seed" in r or "boundary" in r]:
        n = G.nodes[k]
        low = n.rel.lower()
        for a, b in _PAIR:
            for x, y in ((a, b), (b, a)):
                if x in low:
                    mate = by_inst.get(n.inst, {}).get(low.replace(x, y))
                    if mate and mate != k:
                        region.add(mate, "closure:handshake_pair")


# ---------------------------------------------------------------------- driver
# score(v) = max over seeds s of weight(s) * exp(-cost(s, v) / TAU);
# keep v if score >= THRESHOLD[level]
TAU = 1.5  # tuned on 24 session-annotated designs (experiments/e1_trace_tuning/run.py)
THRESHOLD = {Level.HIGH: 0.60, Level.MEDIUM: 0.40, Level.LOW: 0.15}


def compute_region(
    G: DesignGraph,
    tables: dict[str, EntityTable],
    results: dict[str, ModuleResult],
    *,
    level: Level = Level.MEDIUM,
    threshold: float | None = None,
    depth: float = 8.0,
    reg_hops: int = 1,
    include_top_ports: bool = True,
    steiner: bool = False,
    budget: int | None = None,
    edge_fanin: int | None = 4,
    data_max_hops: int | None = 6,
) -> Region:
    region = Region(total_nodes=G.g.number_of_nodes())
    seeds = anchor_seeds(G, tables, results)
    thr = THRESHOLD[level] if threshold is None else threshold
    for k, s in seeds.items():
        region.add(k, "seed")
        region.scores[k] = max(region.scores.get(k, 0.0), s["weight"])
        hint = s["trace"] if isinstance(s["trace"], TraceHint) else TraceHint(s["trace"])
        for nb, cost in typed_slice(
            G, k, hint, depth=depth, reg_hops=reg_hops, stop_at=set(seeds)
        ).items():
            sc = s["weight"] * math.exp(-cost / TAU)
            if sc >= thr:
                region.add(nb, f"slice:{s['module']}.{s['id']}")
                region.scores[nb] = max(region.scores.get(nb, 0.0), sc)
    if steiner and len(seeds) > 1:
        for k in steiner_connect(G, set(seeds)):
            region.add(k, "steiner")
    if include_top_ports:
        for top in G.tops:
            for k in G.instances[top].ports.values():
                region.add(k, "boundary")
    # enable/select closure only for the detailed view; handshake pairs and resets always
    semantic_closure(G, region, control=(level == Level.LOW))
    if budget is not None and len(region.nodes) > budget:
        _apply_budget(region, budget)
    region.anchor_edges = anchor_edges(G, seeds, fanin=edge_fanin, data_max_hops=data_max_hops)
    return region


# ------------------------------------------------------------------ anchor edges
_FLOW = {EdgeType.DATA, EdgeType.CONTROL, EdgeType.ADDR, EdgeType.PORT}


def anchor_edges(
    G: DesignGraph,
    seeds: dict[str, dict] | set[str],
    max_hops: int = 12,
    max_regs: int = 1,
    fanin: int | None = 4,
    data_max_hops: int | None = 6,
) -> list[dict]:
    """Abstract block-diagram edges between anchors: s -> t when s influences t through non-anchor
    nodes only (crossing at most `max_regs` non-anchor registers). kind = control if any CONTROL
    edge is on the path, else addr if any ADDR edge, else data. These carry connectivity to Stage 2
    without putting every intermediate wire into the region."""
    out: dict[tuple[str, str, str], dict] = {}
    for s in seeds:
        # state: (node, regs, has_ctrl, has_addr) ; BFS by hop count
        frontier = [(s, 0, False, False)]
        seen = {(s, 0, False, False)}
        hops = 0
        while frontier and hops < max_hops:
            hops += 1
            nxt = []
            for k, regs, hc, ha in frontier:
                for t, et in G.succs(k, _FLOW):
                    if t == s:
                        continue
                    c2, a2 = hc or et == EdgeType.CONTROL, ha or et == EdgeType.ADDR
                    if t in seeds:
                        kind = "control" if c2 else ("addr" if a2 else "data")
                        key = (s, t, kind)
                        if key not in out or out[key]["hops"] > hops:
                            out[key] = {
                                "src": s,
                                "dst": t,
                                "kind": kind,
                                "hops": hops,
                                "via_regs": regs,
                            }
                        continue
                    r2 = regs + (1 if G.nodes[t].is_state else 0)
                    if r2 > max_regs:
                        continue
                    st = (t, r2, c2, a2)
                    if st not in seen:
                        seen.add(st)
                        nxt.append(st)
            frontier = nxt
    # merge parallel arrows: one arrow per (src, dst) carrying every kind seen
    merged: dict[tuple[str, str], dict] = {}
    for e in out.values():
        m = merged.setdefault(
            (e["src"], e["dst"]),
            {
                "src": e["src"],
                "dst": e["dst"],
                "kinds": [],
                "hops": e["hops"],
                "via_regs": e["via_regs"],
            },
        )
        m["kinds"] = sorted(set(m["kinds"]) | {e["kind"]})
        m["hops"] = min(m["hops"], e["hops"])
        m["via_regs"] = min(m["via_regs"], e["via_regs"])
    # readability pruning: a register inside a giant always-block is reachable from almost every
    # anchor. Per destination keep the `fanin` best sources: data paths first, then shorter, then
    # more important sources. Long pure-data paths are dropped.
    weight = seeds if isinstance(seeds, dict) else {}
    by_dst: dict[str, list[dict]] = {}
    for e in merged.values():
        pure_data = "control" not in e["kinds"]
        if pure_data and data_max_hops is not None and e["hops"] > data_max_hops:
            continue
        by_dst.setdefault(e["dst"], []).append(e)
    keep = []
    for _dst, es in by_dst.items():
        es.sort(
            key=lambda e: (
                "data" not in e["kinds"],
                e["hops"],
                e["via_regs"],
                -weight.get(e["src"], {}).get("weight", 0.0),
                e["src"],
            )
        )
        keep += es if fanin is None else es[:fanin]
    for e in keep:
        e["kind"] = "data" if "data" in e["kinds"] else e["kinds"][0]  # primary kind for drawing
    return sorted(keep, key=lambda e: (e["src"], e["dst"]))


_PRIORITY = ("seed", "boundary", "steiner", "slice", "closure")


def _apply_budget(region: Region, budget: int) -> None:
    def rank(reasons: list[str]) -> int:
        best = len(_PRIORITY)
        for r in reasons:
            for i, p in enumerate(_PRIORITY):
                if r.startswith(p):
                    best = min(best, i)
        return best

    order = sorted(region.nodes.items(), key=lambda kv: rank(kv[1]))
    region.nodes = dict(order[:budget])


def uncovered_hotspots(
    G: DesignGraph, table: EntityTable, region: Region, min_ctrl_fanout: int = 3
) -> list[str]:
    """Refine-round feedback: important-looking entities the region never touched."""
    msgs = []
    for r in table.rows:
        if r.kind == "inst" or r.auto_role:
            continue
        keys = entity_nodes(G, table, r.id)
        if any(k in region.nodes for k in keys):
            continue
        if r.fsm_candidate:
            msgs.append(
                f"{r.id} ({r.name}) looks like an FSM state register "
                "but is outside every traced region"
            )
        elif r.is_state and r.ctrl_fanout >= min_ctrl_fanout:
            msgs.append(
                f"{r.id} ({r.name}) is a register that controls {r.ctrl_fanout} other entities "
                "but is outside every traced region"
            )
        elif r.kind == "mem":
            msgs.append(f"{r.id} ({r.name}) is a memory array outside every traced region")
    return msgs
