"""Quantified importance (SPEC §4.6): a 0-100 score per entity from structure, role and tier.

Structural features are computed on the elaborated dependency graph of the module's
canonical instance and never look at names, so the score is invariant under renaming.
The coefficients are fitted offline (experiments/e5_importance_score) and frozen here.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from .frontend.entities import EntityTable
from .frontend.graph import DesignGraph, EdgeType
from .schema import EntityRow

SCORE_VERSION = "importance-score-v2"

_FLOW = {EdgeType.DATA, EdgeType.CONTROL, EdgeType.ADDR, EdgeType.PORT}
_CTRL = {EdgeType.CONTROL, EdgeType.ADDR}

STRUCT_FEATURES = [
    "log_width",
    "is_state",
    "fsm_candidate",
    "is_mem",
    "port_in",
    "port_out",
    "log_fanin",
    "log_fanout",
    "log_ctrl_fanout",
    "log_addr_fanout",
    "ctrl_reach",
    "any_reach",
    "out_reach",
    "back_cone",
    "ctrl_rank",
    "reach_rank",
    "log_module_size",
]


# Fitted by experiments/e5_importance_score/fit.py (importance-score-v2) on 9,151 teacher anchors
# from 412 distinct modules (rounds 1-4). Grouped-CV AUC MEDIUM 0.82 / HIGH 0.87; on round-4
# modules v2 0.81 / 0.86 vs v1 (fitted without them) 0.79 / 0.84. Weights per raw feature unit.
COEFS: dict[str, dict[str, float]] = {
    "MEDIUM": {
        "bias": 0.9664,
        "log_width": 0.3332,
        "is_state": 0.3594,
        "fsm_candidate": 0.1785,
        "is_mem": 1.3836,
        "port_in": 1.7326,
        "port_out": 2.5286,
        "log_fanin": 0.1712,
        "log_fanout": 0.829,
        "log_ctrl_fanout": -0.2849,
        "log_addr_fanout": 0.4934,
        "ctrl_reach": 1.1727,
        "any_reach": -0.1488,
        "out_reach": 0.4471,
        "back_cone": 1.4969,
        "ctrl_rank": -0.0415,
        "reach_rank": 0.3013,
        "log_module_size": -0.9597,
        "role:FSM_STATE": 3.2401,
        "role:CONTROL_FLAG": -0.1453,
        "role:ENABLE": -0.5434,
        "role:MUX_SELECT": 0.5982,
        "role:COUNTER": 0.6637,
        "role:HANDSHAKE_VALID": 0.8312,
        "role:HANDSHAKE_READY": 0.04,
        "role:INTERFACE_DATA": 0.0743,
        "role:INTERFACE_ADDR": -0.1056,
        "role:DATAPATH_MAJOR": -0.7299,
        "role:PIPELINE_REG": -0.3954,
        "role:STORAGE": 0.7021,
        "role:FIFO_PTR": 0.0742,
        "role:CONFIG_REG": -0.8801,
        "role:ARBITRATION": 0.5531,
        "role:STATUS": -1.272,
        "role:COMMAND": -0.9194,
        "role:INDEX": -1.1733,
        "role:HOLDING_REG": -0.742,
        "role:DECODE": 0.1282,
        "role:CLOCK_GEN": -0.2129,
    },
    "HIGH": {
        "bias": -1.8008,
        "log_width": 0.3545,
        "is_state": 0.2,
        "fsm_candidate": 1.5053,
        "is_mem": 1.5413,
        "port_in": 2.4893,
        "port_out": 3.0412,
        "log_fanin": 0.2318,
        "log_fanout": 0.9455,
        "log_ctrl_fanout": -0.3463,
        "log_addr_fanout": 0.5296,
        "ctrl_reach": 0.761,
        "any_reach": 0.3453,
        "out_reach": -0.0453,
        "back_cone": 2.2027,
        "ctrl_rank": -0.2183,
        "reach_rank": -0.0318,
        "log_module_size": -0.8784,
        "role:FSM_STATE": 4.2139,
        "role:CONTROL_FLAG": -0.5548,
        "role:ENABLE": -1.7091,
        "role:MUX_SELECT": 0.2889,
        "role:COUNTER": 0.2688,
        "role:HANDSHAKE_VALID": 1.2982,
        "role:HANDSHAKE_READY": 0.4672,
        "role:INTERFACE_DATA": 0.6402,
        "role:INTERFACE_ADDR": -0.6452,
        "role:DATAPATH_MAJOR": -0.5385,
        "role:PIPELINE_REG": 0.1096,
        "role:STORAGE": 1.2132,
        "role:FIFO_PTR": 0.0521,
        "role:CONFIG_REG": -1.1743,
        "role:ARBITRATION": 1.8074,
        "role:STATUS": -1.9811,
        "role:COMMAND": -1.3944,
        "role:INDEX": -2.6134,
        "role:HOLDING_REG": -0.7074,
        "role:DECODE": -0.6706,
        "role:CLOCK_GEN": -0.3025,
    },
}


def _nodes_of(G: DesignGraph, t: EntityTable, row: EntityRow) -> list[str]:
    keys = [k for k, eid in t.key_to_id.items() if eid == row.id and k in G.nodes]
    return [k for k in keys if G.nodes[k].inst == t.canonical_instance] or keys


def _sinks(G: DesignGraph, inst: str) -> tuple[set[str], set[str]]:
    state, outs = set(), set()
    for n in G.nodes_of_instance(inst):
        if n.is_state or n.depth is not None:
            state.add(n.key)
        if n.port_dir == "out":
            outs.add(n.key)
    return state, outs


def _forward(G, starts, first_types, stop: set[str], inst: str, max_hops: int = 6) -> set[str]:
    """Nodes of `inst` reached from `starts`; the first edge must be in `first_types`;
    the walk passes through combinational nodes and stops at state elements."""
    seen: set[str] = set()
    q = deque()
    for s in starts:
        for v, et in G.succs(s, _FLOW):
            if et in first_types and G.nodes[v].inst == inst and v not in seen:
                seen.add(v)
                q.append((v, 1))
    while q:
        k, h = q.popleft()
        if k in stop or h >= max_hops:
            continue
        for v, _ in G.succs(k, _FLOW):
            if v not in seen and G.nodes[v].inst == inst:
                seen.add(v)
                q.append((v, h + 1))
    return seen


def _backward(G, starts, inst: str, stop: set[str], max_hops: int = 6) -> set[str]:
    seen: set[str] = set()
    q = deque((s, 0) for s in starts)
    while q:
        k, h = q.popleft()
        if h >= max_hops:
            continue
        for p, _ in G.preds(k, _FLOW):
            if p in seen or G.nodes[p].inst != inst:
                continue
            seen.add(p)
            if p not in stop and G.nodes[p].port_dir != "in":
                q.append((p, h + 1))
    return seen


@dataclass
class _Ctx:
    state: set[str]
    outs: set[str]
    n_sinks: int
    n_nodes: int


def module_features(G: DesignGraph, t: EntityTable) -> dict[str, dict[str, float]]:
    """entity id -> structural feature dict, for every selectable entity of the module."""
    inst = t.canonical_instance
    state, outs = _sinks(G, inst)
    sinks = state | outs
    ctx = _Ctx(state, outs, max(1, len(sinks)), max(1, len(G.nodes_of_instance(inst))))
    rows = [r for r in t.rows if r.kind != "inst" and not r.auto_role]
    raw: dict[str, dict[str, float]] = {}
    for r in rows:
        keys = _nodes_of(G, t, r)
        n0 = G.nodes[keys[0]] if keys else None
        ctrl = _forward(G, keys, _CTRL, ctx.state, inst) & sinks
        anyr = _forward(G, keys, _FLOW, ctx.state, inst) & sinks
        back = _backward(G, keys, inst, ctx.state)
        raw[r.id] = {
            "log_width": math.log2(1 + max(r.width, 1)),
            "is_state": float(r.is_state),
            "fsm_candidate": float(r.fsm_candidate),
            "is_mem": float(r.depth is not None),
            "port_in": float(bool(n0 and n0.port_dir == "in")),
            "port_out": float(bool(n0 and n0.port_dir == "out")),
            "log_fanin": math.log1p(r.fanin),
            "log_fanout": math.log1p(r.fanout),
            "log_ctrl_fanout": math.log1p(r.ctrl_fanout),
            "log_addr_fanout": math.log1p(r.addr_fanout),
            "ctrl_reach": len(ctrl) / ctx.n_sinks,
            "any_reach": len(anyr) / ctx.n_sinks,
            "out_reach": (len(anyr & ctx.outs) / len(ctx.outs)) if ctx.outs else 0.0,
            "back_cone": min(1.0, len(back) / ctx.n_nodes),
            "log_module_size": math.log1p(len(rows)),
        }
    for feat, rank in (("ctrl_reach", "ctrl_rank"), ("any_reach", "reach_rank")):
        vals = sorted(f[feat] for f in raw.values())
        n = len(vals)
        for f in raw.values():
            below = sum(1 for v in vals if v < f[feat])
            f[rank] = below / (n - 1) if n > 1 else 0.5
    return raw


# ---------------------------------------------------------------------------- the score
TIER_POINTS = {"critical": 100.0, "major": 60.0, "minor": 20.0}
STRUCT_WEIGHT = 0.3  # fitted on independent k0/k1 annotation pairs (plateau 0.1-0.4)
# view thresholds on the 0-100 scale (same for every mode)
SCORE_HIGH = 70.0
SCORE_MEDIUM = 40.0
# structure-only scores are mapped so that the teacher's HIGH / MEDIUM shares (27% / 56% of
# anchors, rounds 1-4) fall on the same thresholds: raw 60.4 -> 70, raw 32.8 -> 40
_STRUCT_KNOTS = [(0.0, 0.0), (32.8, SCORE_MEDIUM), (60.4, SCORE_HIGH), (100.0, 100.0)]


def _prob(target: str, feats: dict[str, float], role: str | None) -> float:
    w = COEFS[target]
    z = w["bias"] + sum(w[f] * feats[f] for f in STRUCT_FEATURES)
    if role is not None:
        z += w.get(f"role:{role}", 0.0)
    return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, z))))


def structural_score(feats: dict[str, float], role: str | None) -> float:
    """0-100 from structure + role only: 50*P(teacher puts it in MEDIUM) + 50*P(in HIGH)."""
    return 50.0 * _prob("MEDIUM", feats, role) + 50.0 * _prob("HIGH", feats, role)


def calibrated_structural(struct: float) -> float:
    for (x0, y0), (x1, y1) in zip(_STRUCT_KNOTS, _STRUCT_KNOTS[1:], strict=False):
        if struct <= x1:
            return y0 + (y1 - y0) * (struct - x0) / (x1 - x0)
    return 100.0


def combined_score(struct: float, tier: str | None, weight: float = STRUCT_WEIGHT) -> float:
    """Final 0-100 importance. Without a tier (structure-only mode) it is the calibrated
    structural score; with one it is `weight * structural + (1 - weight) * tier points`."""
    if tier is None:
        return round(calibrated_structural(struct), 1)
    return round(weight * struct + (1.0 - weight) * TIER_POINTS[tier], 1)


def score_module(G: DesignGraph, t: EntityTable, anchors, weight: float = STRUCT_WEIGHT):
    """{anchor id: (combined score, structure-only score)}, both 0-100, for one module."""
    feats = module_features(G, t)
    out = {}
    for a in anchors:
        f = feats.get(a.id)
        if f is None:
            continue
        role = a.role.value if hasattr(a.role, "value") else a.role
        tier = a.importance.value if hasattr(a.importance, "value") else a.importance
        st = structural_score(f, role)
        out[a.id] = (combined_score(st, tier, weight), combined_score(st, None))
    return out


def attach_scores(G: DesignGraph, tables: dict, results: dict) -> None:
    """Fill `score` / `struct_score` of every anchor in-place (results: module -> ModuleResult)."""
    for mod, res in results.items():
        t = tables.get(mod)
        if t is None:
            continue
        sc = score_module(G, t, res.anchors)
        for a in res.anchors:
            if a.id in sc:
                a.score, a.struct_score = sc[a.id]
