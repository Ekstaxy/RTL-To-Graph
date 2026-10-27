"""Gold-set evaluation (SPEC §10)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from .frontend.entities import EntityTable
from .frontend.graph import DesignGraph
from .schema import ModuleResult
from .taxonomy import Importance, Level, Role
from .trace import Region, entity_nodes


class GoldAnchor(BaseModel):
    id: str
    name: str
    role: Role
    importance: Importance
    alt_ids: list[str] = Field(default_factory=list)


class GoldGroup(BaseModel):
    name: str
    anchor_ids: list[str]


class GoldModule(BaseModel):
    module: str
    level: Level = Level.MEDIUM
    status: str = "draft"
    anchors: list[GoldAnchor]
    groups: list[GoldGroup] = Field(default_factory=list)


def load_gold(gold_dir: str | Path) -> dict[str, GoldModule]:
    out = {}
    for p in sorted(Path(gold_dir).glob("*.json")):
        g = GoldModule.model_validate_json(p.read_text(encoding="utf-8"))
        out[g.module] = g
    return out


@dataclass
class ModuleScore:
    module: str
    concepts: int
    hit: int
    predicted: int
    precise: int
    role_ok: int
    groups: int = 0
    groups_hit: int = 0
    trace_cov: float | None = None
    misses: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)
    role_errors: list[str] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.hit / self.concepts if self.concepts else 1.0

    @property
    def precision(self) -> float:
        return self.precise / self.predicted if self.predicted else 1.0

    @property
    def role_acc(self) -> float:
        return self.role_ok / self.hit if self.hit else 1.0


def score_module(
    gold: GoldModule,
    pred: ModuleResult,
    table: EntityTable | None = None,
    graph: DesignGraph | None = None,
    region: Region | None = None,
) -> ModuleScore:
    rows = table.by_id() if table else {}
    concepts = [({g.id, *g.alt_ids}, g) for g in gold.anchors]
    pred_by_id = {a.id: a for a in pred.anchors}
    s = ModuleScore(
        module=gold.module,
        concepts=len(concepts),
        hit=0,
        predicted=len(pred.anchors),
        precise=0,
        role_ok=0,
    )
    for ids, g in concepts:
        hits = [pred_by_id[i] for i in sorted(ids) if i in pred_by_id]
        if hits:
            s.hit += 1
            best = next((h for h in hits if h.id == g.id), hits[0])
            if best.role == g.role:
                s.role_ok += 1
            else:
                s.role_errors.append(f"{g.name}: gold {g.role.value} vs pred {best.role.value}")
        else:
            s.misses.append(f"{g.id}:{g.name}({g.role.value})")
    covered = set().union(*(ids for ids, _ in concepts)) if concepts else set()
    for a in pred.anchors:
        if a.id in covered:
            s.precise += 1
        else:
            s.extras.append(f"{a.id}:{rows[a.id].name if a.id in rows else a.name}({a.role.value})")
    # groups: a gold group is hit if some predicted group has anchor-Jaccard >= 0.5
    # (concept-expanded)
    concept_of = {}
    for i, (ids, _) in enumerate(concepts):
        for x in ids:
            concept_of[x] = i

    def cset(xs):
        return {concept_of[x] for x in xs if x in concept_of}

    s.groups = len(gold.groups)
    for gg in gold.groups:
        gc = cset(gg.anchor_ids)
        for pg in pred.groups:
            pc = cset(pg.anchor_ids + pg.member_ids)
            if gc and len(gc & pc) / len(gc | pc) >= 0.5:
                s.groups_hit += 1
                break
    if graph is not None and region is not None and table is not None:
        tot = cov = 0
        for ids, _ in concepts:
            keys = [k for i in ids for k in entity_nodes(graph, table, i)]
            if keys:
                tot += 1
                cov += any(k in region.nodes for k in keys)
        s.trace_cov = cov / tot if tot else None
    return s


def summarize(scores: list[ModuleScore]) -> dict:
    C = sum(s.concepts for s in scores)
    H = sum(s.hit for s in scores)
    P = sum(s.predicted for s in scores)
    PP = sum(s.precise for s in scores)
    R = sum(s.role_ok for s in scores)
    G = sum(s.groups for s in scores)
    GH = sum(s.groups_hit for s in scores)
    tc = [s.trace_cov for s in scores if s.trace_cov is not None]
    return {
        "modules": len(scores),
        "concept_recall": round(H / C, 4) if C else None,
        "anchor_precision": round(PP / P, 4) if P else None,
        "role_accuracy": round(R / H, 4) if H else None,
        "group_recall": round(GH / G, 4) if G else None,
        "trace_coverage": round(sum(tc) / len(tc), 4) if tc else None,
    }


def report_markdown(name: str, scores: list[ModuleScore]) -> str:
    sm = summarize(scores)
    lines = [f"## {name}", "", "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sm.items()]
    lines += [
        "",
        "| module | recall | precision | role acc | groups | trace cov | misses | extras "
        "| role errors |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        tc = f"{s.trace_cov:.2f}" if s.trace_cov is not None else "-"
        lines.append(
            f"| {s.module} | {s.recall:.2f} | {s.precision:.2f} | {s.role_acc:.2f} | "
            f"{s.groups_hit}/{s.groups} | {tc} | "
            f"{', '.join(s.misses) or '-'} | {', '.join(s.extras) or '-'} | "
            f"{'; '.join(s.role_errors) or '-'} |"
        )
    return "\n".join(lines)


def dump_scores(scores: list[ModuleScore]) -> str:
    return json.dumps(
        {
            "summary": summarize(scores),
            "modules": [
                s.__dict__ | {"recall": s.recall, "precision": s.precision, "role_acc": s.role_acc}
                for s in scores
            ],
        },
        indent=2,
    )
