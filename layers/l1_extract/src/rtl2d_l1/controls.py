"""User controls (SPEC §4.5): deterministic views over a full-detail annotation.

The teacher always annotates at full detail (LOW) with careful importance tiers.
Everything the user can tune -- level, anchor caps, role focus, trace aggressiveness --
is applied *afterwards*, so one paid annotation serves every view and the views are
guaranteed nested (HIGH ⊆ MEDIUM ⊆ LOW).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .frontend.entities import EntityTable
from .importance import SCORE_HIGH, SCORE_MEDIUM, TIER_POINTS
from .schema import ModuleResult, VotedAnchor
from .taxonomy import LEVEL_ALLOWED_IMPORTANCE, LEVEL_MAX_GROUPS, Level, Role

INTERFACE_ROLES = {
    Role.HANDSHAKE_VALID,
    Role.HANDSHAKE_READY,
    Role.INTERFACE_DATA,
    Role.INTERFACE_ADDR,
}

# presets for users who do not want to tune individual knobs
PRESETS = {
    "overview": dict(level=Level.HIGH, max_anchors=6, max_groups=4),
    "standard": dict(level=Level.MEDIUM),
    "detailed": dict(level=Level.LOW),
    "control": dict(
        level=Level.MEDIUM,
        include_roles={
            Role.FSM_STATE,
            Role.CONTROL_FLAG,
            Role.ENABLE,
            Role.MUX_SELECT,
            Role.COUNTER,
            Role.ARBITRATION,
            Role.HANDSHAKE_VALID,
            Role.HANDSHAKE_READY,
        },
    ),
    "datapath": dict(
        level=Level.MEDIUM,
        include_roles={
            Role.DATAPATH_MAJOR,
            Role.PIPELINE_REG,
            Role.STORAGE,
            Role.FIFO_PTR,
            Role.INTERFACE_DATA,
            Role.INTERFACE_ADDR,
        },
    ),
}


IMPORTANCE_MODES = ("score", "tier", "structure")


@dataclass
class Controls:
    level: Level = Level.MEDIUM
    # how a level is decided (SPEC §4.6):
    #   score     - 0-100 quantified score (structure + role + annotator tier);
    #               HIGH >= 70, MEDIUM >= 40
    #   tier      - the annotator's tier only (critical / major / minor), the v1.5 behaviour
    #   structure - structure + role only, ignores the annotator's tier (weak annotators)
    importance: str = "score"
    min_score: float | None = None  # extra floor on the 0-100 score
    # anchor view
    max_anchors: int | None = None  # per module; keeps the most important first
    min_confidence: float = 0.0  # k-voting confidence floor
    include_roles: set[Role] | None = None  # focus: only these roles
    exclude_roles: set[Role] = field(default_factory=set)
    hide_interfaces: bool = (
        False  # drop port-level roles from anchors (bundles stay in `interfaces`)
    )
    max_groups: int | None = None
    # trace
    threshold: float | None = None  # override the per-level relevance threshold
    depth: float = 8.0
    reg_hops: int = 1
    steiner: bool = False  # connectivity is carried by region.anchor_edges instead
    include_ports: bool = True
    max_region_nodes: int | None = None
    # abstract anchor -> anchor edges (block-diagram arrows)
    edge_fanin: int | None = 4  # arrows kept per destination anchor (None = all)
    edge_data_max_hops: int | None = 6  # data arrows longer than this are dropped (None = keep)

    @classmethod
    def preset(cls, name: str, **over) -> Controls:
        kw = dict(PRESETS[name])
        kw.update(over)
        return cls(**kw)

    def describe(self) -> dict:
        d = {
            k: (
                sorted(r.value for r in v)
                if isinstance(v, set)
                else (v.value if isinstance(v, Level) else v)
            )
            for k, v in self.__dict__.items()
        }
        return d


def importance_of(a: VotedAnchor, mode: str) -> float:
    """0-100 importance of an anchor under an importance mode (tier points when unscored)."""
    if mode == "score" and a.score is not None:
        return a.score
    if mode == "structure" and a.struct_score is not None:
        return a.struct_score
    return TIER_POINTS[a.importance.value]


def _level_ok(a: VotedAnchor, c: Controls) -> bool:
    if c.importance == "tier":
        return a.importance in LEVEL_ALLOWED_IMPORTANCE[c.level]
    s = importance_of(a, c.importance)
    floor = {Level.HIGH: SCORE_HIGH, Level.MEDIUM: SCORE_MEDIUM, Level.LOW: 0.0}[c.level]
    return s >= floor


def _rank_key(a: VotedAnchor, table: EntityTable | None, mode: str = "score"):
    row = table.by_id().get(a.id) if table else None
    return (
        -importance_of(a, mode),
        -a.confidence,
        -(row.ctrl_fanout + row.fanout if row else 0),
        int(a.id[1:]) if a.id[1:].isdigit() else 0,
    )


def apply_view(res: ModuleResult, c: Controls, table: EntityTable | None = None) -> ModuleResult:
    if c.importance not in IMPORTANCE_MODES:
        raise ValueError(f"importance must be one of {IMPORTANCE_MODES}")
    keep = [
        a
        for a in res.anchors
        if _level_ok(a, c)
        and (c.min_score is None or importance_of(a, c.importance) >= c.min_score)
        and a.confidence >= c.min_confidence
        and (c.include_roles is None or a.role in c.include_roles)
        and a.role not in c.exclude_roles
        and not (c.hide_interfaces and a.role in INTERFACE_ROLES)
    ]
    if c.max_anchors is not None and len(keep) > c.max_anchors:
        keep = sorted(keep, key=lambda a: _rank_key(a, table, c.importance))[: c.max_anchors]
    keep.sort(key=lambda a: int(a.id[1:]) if a.id[1:].isdigit() else 0)
    ids = {a.id for a in keep}
    groups = []
    for g in res.groups:
        gi = [x for x in g.anchor_ids if x in ids]
        if gi:
            groups.append(g.model_copy(update={"anchor_ids": gi}))
    cap = c.max_groups if c.max_groups is not None else LEVEL_MAX_GROUPS[c.level]
    groups.sort(
        key=lambda g: -max(importance_of(a, c.importance) for a in keep if a.id in g.anchor_ids)
    )
    groups = groups[:cap]
    return res.model_copy(update={"anchors": keep, "groups": groups, "level": c.level})


_ORDER = [Level.HIGH, Level.MEDIUM, Level.LOW]


def region_for(G, tables: dict, full_results: dict, c: Controls):
    """Trace region for the requested view, guaranteed nested:
    region(HIGH) ⊆ region(MEDIUM) ⊆ region(LOW).

    A finer level adds anchors (and lowers the relevance threshold) but also adds stop points and
    a different Steiner tree, so it is computed as the union with every coarser level."""
    from dataclasses import replace as _replace

    from .trace import compute_region

    region = None
    for lv in _ORDER[: _ORDER.index(c.level) + 1]:
        cl = _replace(c, level=lv)
        views = {m: apply_view(r, cl, tables.get(m)) for m, r in full_results.items()}
        r = compute_region(
            G,
            tables,
            views,
            level=lv,
            threshold=c.threshold if lv == c.level else None,
            depth=c.depth,
            reg_hops=c.reg_hops,
            steiner=c.steiner,
            include_top_ports=c.include_ports,
            edge_fanin=c.edge_fanin,
            data_max_hops=c.edge_data_max_hops,
        )
        if region is None:
            region = r
        else:
            region.merge(r)
    if c.max_region_nodes is not None and len(region.nodes) > c.max_region_nodes:
        from .trace import _apply_budget

        _apply_budget(region, c.max_region_nodes)
    return region
