"""Tune trace thresholds against session-teacher annotations (no API).

For each level L the region should
  * cover every anchor allowed at L (seeds; always true),
  * NOT already swallow most anchors that only exist at the finer level ("leak"):
      leak(HIGH)   = share of major-only anchors inside the HIGH region
      leak(MEDIUM) = share of minor-only anchors inside the MEDIUM region
  * reduce the internal (non-port) graph as much as possible.

usage: python experiments/e1_trace_tuning/run.py <manifest> [<manifest> ...]
"""

import json
import statistics as st
import sys
from pathlib import Path

from rtl2d_l1 import trace
from rtl2d_l1.cli import main as _  # noqa: F401  (ensures package import side effects)
from rtl2d_l1.controls import Controls, region_for
from rtl2d_l1.llm.teacher import TeacherConfig
from rtl2d_l1.pipeline import RunConfig, annotate_design
from rtl2d_l1.store import RunStore
from rtl2d_l1.taxonomy import Level
from rtl2d_l1.trace import entity_nodes

designs = []
for m in sys.argv[1:]:
    base = Path(m).parent
    for it in json.loads(Path(m).read_text(encoding="utf-8")):
        designs.append(
            {
                "name": it.get("name") or it["top"],
                "files": [str(base / f) for f in it["files"]],
                "top": it.get("top"),
                "spec": str(base / it["spec"]) if it.get("spec") else None,
            }
        )

cfg = RunConfig(
    mode="teacher",
    store_only=True,
    refine=False,
    teacher=TeacherConfig(model="claude-session", effort="session"),
)
store = RunStore()
runs = []
for d in designs:
    spec = Path(d["spec"]).read_text(encoding="utf-8", errors="replace") if d["spec"] else None
    run = annotate_design(d["files"], top=d["top"], cfg=cfg, store=store, name=d["name"], spec=spec)
    if (
        any(r.source == "teacher" for r in run.results_full.values())
        and run.graph.g.number_of_nodes() >= 12
    ):
        runs.append(run)
print(f"{len(runs)} teacher-annotated designs with >= 12 nodes")

IMP = {"HIGH": {"critical"}, "MEDIUM": {"critical", "major"}, "LOW": {"critical", "major", "minor"}}
FINER_ONLY = {"HIGH": {"major"}, "MEDIUM": {"minor"}}


def evaluate(thr: dict, tau: float):
    trace.TAU = tau
    old = dict(trace.THRESHOLD)
    trace.THRESHOLD.update(thr)
    out = {lv: {"red": [], "leak": []} for lv in ("HIGH", "MEDIUM", "LOW")}
    for run in runs:
        tb = run.tables_by_module
        for lv in Level:
            r = region_for(run.graph, tb, run.results_full, Controls(level=lv))
            out[lv.value]["red"].append(r.internal_reduction(run.graph))
            if lv.value in FINER_ONLY:
                tot = hit = 0
                for m, res in run.results_full.items():
                    if res.source != "teacher":
                        continue
                    for a in res.anchors:
                        if a.importance.value in FINER_ONLY[lv.value]:
                            keys = entity_nodes(run.graph, tb[m], a.id)
                            if keys:
                                tot += 1
                                hit += any(k in r.nodes for k in keys)
                if tot:
                    out[lv.value]["leak"].append(hit / tot)
    trace.THRESHOLD.clear()
    trace.THRESHOLD.update(old)
    return {
        lv: (round(st.median(v["red"]), 3), round(st.mean(v["leak"]), 3) if v["leak"] else None)
        for lv, v in out.items()
    }


grid = [
    ({Level.HIGH: 0.45, Level.MEDIUM: 0.25, Level.LOW: 0.10}, 2.0),  # v1.3 defaults
    ({Level.HIGH: 0.50, Level.MEDIUM: 0.30, Level.LOW: 0.10}, 1.5),
    ({Level.HIGH: 0.60, Level.MEDIUM: 0.30, Level.LOW: 0.10}, 1.5),
    ({Level.HIGH: 0.60, Level.MEDIUM: 0.35, Level.LOW: 0.10}, 2.0),
    ({Level.HIGH: 0.60, Level.MEDIUM: 0.40, Level.LOW: 0.15}, 1.5),
    ({Level.HIGH: 0.70, Level.MEDIUM: 0.45, Level.LOW: 0.15}, 1.5),
    ({Level.HIGH: 0.80, Level.MEDIUM: 0.50, Level.LOW: 0.20}, 1.5),
    ({Level.HIGH: 0.70, Level.MEDIUM: 0.50, Level.LOW: 0.20}, 1.0),
]
print("thresholds(H/M/L) tau | HIGH red,leak(major) | MEDIUM red,leak(minor) | LOW red")
for thr, tau in grid:
    res = evaluate(thr, tau)
    t = "/".join(str(thr[lv]) for lv in Level)
    print(f"{t:16s} {tau:3.1f} | {res['HIGH']} | {res['MEDIUM']} | {res['LOW'][0]}")


if "--ablate" in sys.argv:
    print("\nablation at 0.7/0.5/0.2 tau 1.0 (MEDIUM):")
    trace.THRESHOLD.update({Level.HIGH: 0.7, Level.MEDIUM: 0.5, Level.LOW: 0.2})
    trace.TAU = 1.0
    orig_closure = trace.semantic_closure
    for name, steiner, closure in [
        ("full", True, True),
        ("no steiner", False, True),
        ("no closure", True, False),
        ("seeds+slices only", False, False),
    ]:
        trace.semantic_closure = orig_closure if closure else (lambda G, region: None)
        reds, leaks = [], []
        for run in runs:
            tb = run.tables_by_module
            r = region_for(
                run.graph, tb, run.results_full, Controls(level=Level.MEDIUM, steiner=steiner)
            )
            reds.append(r.internal_reduction(run.graph))
            tot = hit = 0
            for m, res in run.results_full.items():
                for a in res.anchors:
                    if res.source == "teacher" and a.importance.value == "minor":
                        keys = entity_nodes(run.graph, tb[m], a.id)
                        if keys:
                            tot += 1
                            hit += any(k in r.nodes for k in keys)
            if tot:
                leaks.append(hit / tot)
        print(f"  {name:18s} red {st.median(reds):.3f}  leak {st.mean(leaks):.3f}")
    trace.semantic_closure = orig_closure
