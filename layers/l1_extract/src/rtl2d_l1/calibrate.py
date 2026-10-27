"""Calibration: is the output too detailed or too strict? (no API)

For every design in the given manifests (teacher results taken from the Run Store):
  * anchor density per level (anchors / selectable entities),
  * region size / reduction per level and nesting HIGH ⊆ MEDIUM ⊆ LOW,
  * teacher vs heuristic agreement,
  * robustness: original vs renamed variant (same IDs) per level,
  * gold scores where gold exists.
"""

from __future__ import annotations

import json
import statistics as st
from dataclasses import replace
from pathlib import Path

from .controls import Controls, apply_view, region_for
from .evaluate import load_gold, score_module, summarize
from .heuristic import heuristic_annotation
from .llm.teacher import TeacherConfig
from .pipeline import RunConfig, annotate_design
from .schema import ModuleResult, VotedAnchor
from .store import RunStore
from .taxonomy import Level

# density bands for a "normal block diagram" (MEDIUM), as a fraction of selectable entities
DENSITY_TOO_HIGH = 0.60
DENSITY_TOO_LOW = 0.10


def _jacc(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a | b) else 1.0


def _selectable(t) -> int:
    return sum(1 for r in t.rows if r.kind != "inst" and not r.auto_role)


def calibrate(
    designs: list[dict],
    *,
    store: RunStore,
    model: str,
    effort: str,
    base: Controls,
    gold_dir: str | None = None,
) -> dict:
    cfg = RunConfig(
        mode="teacher",
        store_only=True,
        refine=False,
        teacher=TeacherConfig(model=model, effort=effort),
        controls=base,
    )
    gold = load_gold(gold_dir) if gold_dir else {}
    rows, gold_scores, heur_scores = [], {lv: [] for lv in Level}, []
    per_design_full: dict[str, dict[str, ModuleResult]] = {}
    for d in designs:
        spec = (
            Path(d["spec"]).read_text(encoding="utf-8", errors="replace") if d.get("spec") else None
        )
        run = annotate_design(
            d["files"],
            top=d["top"],
            include_dirs=d.get("include_dirs"),
            defines=d.get("defines"),
            cfg=cfg,
            store=store,
            name=d["name"],
            spec=spec,
        )
        tb = run.tables_by_module
        per_design_full[d["name"]] = run.results_full
        regions = {}
        for lv in Level:
            c = replace(base, level=lv)
            views = {m: apply_view(r, c, tb.get(m)) for m, r in run.results_full.items()}
            regions[lv] = (views, region_for(run.graph, tb, run.results_full, c))
        for m, full in run.results_full.items():
            t = tb[m]
            sel = max(1, _selectable(t))
            h = heuristic_annotation(t, Level.LOW)
            hv = apply_view(
                ModuleResult(
                    module=m,
                    canonical_instance=t.canonical_instance,
                    source="heuristic",
                    anchors=[VotedAnchor(**a.model_dump()) for a in h.anchors],
                ),
                replace(base, level=Level.MEDIUM),
                t,
            )
            row = {
                "design": d["name"],
                "module": m,
                "source": full.source,
                "entities": sel,
                "nodes": run.graph.g.number_of_nodes(),
            }
            for lv in Level:
                v = regions[lv][0][m]
                row[f"n_{lv.value}"] = len(v.anchors)
                row[f"dens_{lv.value}"] = round(len(v.anchors) / sel, 3)
            row["teacher_vs_heur_MEDIUM"] = round(
                _jacc(
                    {a.id for a in regions[Level.MEDIUM][0][m].anchors}, {a.id for a in hv.anchors}
                ),
                3,
            )
            row["warnings"] = [w for w in full.warnings if w.startswith("W_")]
            rows.append(row)
            if (
                m in gold
                and full.source == "teacher"
                and not d["name"].startswith(("ren_", "blind_"))
            ):
                for lv in Level:
                    gold_scores[lv].append(
                        score_module(gold[m], regions[lv][0][m], t, run.graph, regions[lv][1])
                    )
                heur_scores.append(score_module(gold[m], hv, t))
        for lv in Level:
            r = regions[lv][1]
            for row in rows:
                if row["design"] == d["name"]:
                    row[f"red_{lv.value}"] = round(r.internal_reduction(run.graph), 3)
        nest = (
            set(regions[Level.HIGH][1].nodes)
            <= set(regions[Level.MEDIUM][1].nodes)
            <= set(regions[Level.LOW][1].nodes)
        )
        for row in rows:
            if row["design"] == d["name"]:
                row["region_nested"] = nest

    # robustness: ren_<x> vs <x> (same module, same IDs)
    robust = []
    for name, full in per_design_full.items():
        if not name.startswith(("ren_", "blind_")):
            continue
        orig_name = name.split("_", 1)[1]
        orig = per_design_full.get(orig_name)
        if not orig:
            continue
        for m, rv in full.items():
            ro = orig.get(m) or (
                next(iter(orig.values())) if len(orig) == 1 and len(full) == 1 else None
            )
            if ro is None or rv.source != "teacher" or ro.source != "teacher":
                continue
            item = {"design": name, "module": m}
            for lv in Level:
                c = replace(base, level=lv)
                a = {x.id: x for x in apply_view(ro, c).anchors}
                b = {x.id: x for x in apply_view(rv, c).anchors}
                item[f"jacc_{lv.value}"] = round(_jacc(set(a), set(b)), 3)
                both = set(a) & set(b)
                item[f"role_agree_{lv.value}"] = (
                    round(sum(a[i].role == b[i].role for i in both) / len(both), 3)
                    if both
                    else None
                )
            robust.append(item)

    teach = [r for r in rows if r["source"] == "teacher"]
    summary = {"modules": len(rows), "teacher_modules": len(teach)}
    for lv in Level:
        if teach:
            ds = [r[f"dens_{lv.value}"] for r in teach]
            ns = [r[f"n_{lv.value}"] for r in teach]
            summary[f"{lv.value}_anchors_median"] = st.median(ns)
            summary[f"{lv.value}_density_median"] = round(st.median(ds), 3)
            big = [r for r in teach if r["nodes"] >= 20]
            if big:
                summary[f"{lv.value}_reduction_median(>=20 nodes)"] = round(
                    st.median(r[f"red_{lv.value}"] for r in big), 3
                )
        if gold_scores[lv]:
            summary[f"gold_{lv.value}"] = summarize(gold_scores[lv])
    if heur_scores:
        summary["gold_heuristic_MEDIUM"] = summarize(heur_scores)
    if teach:
        # a MEDIUM view must read as ONE block diagram: <= 12 anchors
        # (<= 20 for modules with >= 60 entities);
        # it must also not be trivially empty for a module with real content
        summary["too_detailed_MEDIUM"] = [
            f"{r['design']}/{r['module']}={r['n_MEDIUM']}"
            for r in teach
            if r["n_MEDIUM"] > (20 if r["entities"] >= 60 else 12)
        ]
        summary["too_sparse_MEDIUM"] = [
            f"{r['design']}/{r['module']}={r['n_MEDIUM']}"
            for r in teach
            if r["n_MEDIUM"] < 2 and r["entities"] >= 8
        ]
        summary["empty_HIGH"] = [f"{r['design']}/{r['module']}" for r in teach if r["n_HIGH"] == 0]
        summary["region_not_nested"] = sorted(
            {r["design"] for r in teach if not r.get("region_nested", True)}
        )
        summary["teacher_vs_heuristic_MEDIUM_median"] = round(
            st.median(r["teacher_vs_heur_MEDIUM"] for r in teach), 3
        )
    if robust:
        for lv in Level:
            summary[f"robust_jaccard_{lv.value}_mean"] = round(
                st.mean(x[f"jacc_{lv.value}"] for x in robust), 3
            )
    from .versions import TAXONOMY_VERSION

    agr = annotator_agreement(store, model, TAXONOMY_VERSION)
    summary["agreement"] = agr["summary"]
    return {
        "summary": summary,
        "rows": rows,
        "robust": robust,
        "agreement": agr,
        "gold": {lv.value: [s.__dict__ for s in gold_scores[lv]] for lv in Level},
    }


def annotator_agreement(store: RunStore, model: str, taxonomy_version: str) -> dict:
    """Inter-annotator agreement between independent samples (k0 vs k1) of the same work unit."""
    by: dict[str, dict[int, dict]] = {}
    for r in store.iter_records():
        if (
            r.request.get("model") != model
            or r.request.get("round", 0) != 0
            or r.response.get("parsed") is None
            or r.validation.get("errors")
            or r.request.get("taxonomy_version") != taxonomy_version
        ):
            continue
        by.setdefault(r.unit_hash, {})[r.request.get("k_index", 0)] = {
            "rec": r,
            "ann": r.response["parsed"],
        }
    allowed = {
        "HIGH": {"critical"},
        "MEDIUM": {"critical", "major"},
        "LOW": {"critical", "major", "minor"},
    }
    items = []
    for _uh, ks in by.items():
        if 0 not in ks or 1 not in ks:
            continue
        a0, a1 = ks[0]["ann"], ks[1]["ann"]
        it = {"design": ks[0]["rec"].design.get("name"), "module": ks[0]["rec"].module}
        for lv, imp in allowed.items():
            s0 = {x["id"]: x for x in a0["anchors"] if x["importance"] in imp}
            s1 = {x["id"]: x for x in a1["anchors"] if x["importance"] in imp}
            it[f"jacc_{lv}"] = round(_jacc(set(s0), set(s1)), 3)
        f0 = {x["id"]: x for x in a0["anchors"]}
        f1 = {x["id"]: x for x in a1["anchors"]}
        both = set(f0) & set(f1)
        it["role_agree"] = (
            round(sum(f0[i]["role"] == f1[i]["role"] for i in both) / len(both), 3)
            if both
            else None
        )
        it["importance_agree"] = (
            round(sum(f0[i]["importance"] == f1[i]["importance"] for i in both) / len(both), 3)
            if both
            else None
        )
        it["n0"], it["n1"] = len(f0), len(f1)
        items.append(it)
    summ = {}
    if items:
        for k in ("jacc_HIGH", "jacc_MEDIUM", "jacc_LOW", "role_agree", "importance_agree"):
            vals = [x[k] for x in items if x[k] is not None]
            summ[k + "_mean"] = round(st.mean(vals), 3) if vals else None
        summ["pairs"] = len(items)
    return {"summary": summ, "items": items}


def markdown(rep: dict) -> str:
    s = rep["summary"]
    out = [
        "# Calibration report",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(s, indent=2),
        "```",
        "",
    ]
    out += [
        "## Per module (teacher)",
        "",
        "| design | module | ent | HIGH | MED | LOW | dens MED | red H/M/L | vs heur | warnings |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rep["rows"]:
        if r["source"] != "teacher":
            continue
        out.append(
            f"| {r['design']} | {r['module']} | {r['entities']} | "
            f"{r['n_HIGH']} | {r['n_MEDIUM']} | {r['n_LOW']} | "
            f"{r['dens_MEDIUM']:.2f} | {r.get('red_HIGH', 0):.2f}/"
            f"{r.get('red_MEDIUM', 0):.2f}/{r.get('red_LOW', 0):.2f} | "
            f"{r['teacher_vs_heur_MEDIUM']:.2f} | "
            f"{'; '.join(w.split(':')[0] for w in r['warnings']) or '-'} |"
        )
    agr = rep.get("agreement", {})
    if agr.get("items"):
        out += [
            "",
            "## Inter-annotator agreement (independent k0 vs k1)",
            "",
            "```json",
            json.dumps(agr["summary"], indent=2),
            "```",
            "",
            "| design | module | n0 | n1 | Jacc HIGH | Jacc MED | Jacc LOW | role | importance |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for x in agr["items"]:
            out.append(
                f"| {x['design']} | {x['module']} | {x['n0']} | {x['n1']} | "
                f"{x['jacc_HIGH']} | {x['jacc_MEDIUM']} | "
                f"{x['jacc_LOW']} | {x['role_agree']} | {x['importance_agree']} |"
            )
    if rep["robust"]:
        out += [
            "",
            "## Robustness (original vs fully renamed, by entity ID)",
            "",
            "| design | module | Jacc HIGH | Jacc MED | Jacc LOW | role agree MED |",
            "|---|---|---|---|---|---|",
        ]
        for x in rep["robust"]:
            out.append(
                f"| {x['design']} | {x['module']} | {x['jacc_HIGH']} | {x['jacc_MEDIUM']} | "
                f"{x['jacc_LOW']} | {x['role_agree_MEDIUM']} |"
            )
    return "\n".join(out) + "\n"
