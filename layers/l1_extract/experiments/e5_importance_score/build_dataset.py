"""Build the e5 dataset: one row per selectable entity of every teacher-annotated module.

    python experiments/e5_importance_score/build_dataset.py [--model claude-session]

Label = the teacher's voted tier (critical / major / minor / none), plus role and confidence.
Rows of renamed / rewritten variants share a `group` with their original so that
cross-validation never trains on a variant of the test circuit.
"""

import argparse
import json
import re
from pathlib import Path

from rtl2d_l1.importance import module_features
from rtl2d_l1.llm.teacher import TeacherConfig
from rtl2d_l1.pipeline import RunConfig, annotate_design
from rtl2d_l1.store import RunStore

L1 = Path(__file__).resolve().parents[2]
MANIFESTS = [
    "examples/corpus.json",
    "data/corpus/opensource.json",
    "experiments/e3_perturb_benchmark/data/manifest_orig.json",
    "experiments/e3_perturb_benchmark/data/manifest_S1.json",
    "experiments/e3_perturb_benchmark/data/manifest_S2.json",
    "data/corpus/round4_all.json",
]


def designs():
    for m in MANIFESTS:
        mp = L1 / m
        for it in json.loads(mp.read_text(encoding="utf-8")):
            yield (
                m,
                {
                    "name": it.get("name") or it["top"],
                    "files": [str(mp.parent / f) for f in it["files"]],
                    "top": it.get("top"),
                    "include_dirs": [str(mp.parent / d) for d in it.get("include_dirs", [])],
                    "defines": it.get("defines", []),
                },
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-session")
    ap.add_argument("--effort", default="session")
    ap.add_argument("--out", default="runs/e5/dataset.jsonl")
    a = ap.parse_args()
    cfg = RunConfig(
        mode="teacher",
        store_only=True,
        refine=False,
        teacher=TeacherConfig(model=a.model, effort=a.effort),
    )
    store = RunStore(L1 / "runs/store")
    out = L1 / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    n_rows = n_mod = 0
    with out.open("w", encoding="utf-8") as fh:
        for manifest, d in designs():
            run = annotate_design(
                d["files"],
                top=d["top"],
                include_dirs=d["include_dirs"],
                defines=d["defines"],
                cfg=cfg,
                store=store,
                name=d["name"],
            )
            tables = run.tables_by_module
            group = re.sub(r"^(orig|S1|S2)_", "", d["name"])
            group = group.split("_", 1)[-1] if manifest.endswith("round4_all.json") else group
            for mod, res in run.results_full.items():
                if res.source != "teacher" or mod not in tables:
                    continue
                n_mod += 1
                t = tables[mod]
                feats = module_features(run.graph, t)
                lab = {x.id: x for x in res.anchors}
                for eid, f in feats.items():
                    x = lab.get(eid)
                    rec = {
                        "manifest": manifest,
                        "design": d["name"],
                        "group": group,
                        "module": mod,
                        "id": eid,
                        "name": t.by_id()[eid].name,
                        "tier": x.importance.value if x else "none",
                        "role": x.role.value if x else None,
                        "confidence": x.confidence if x else None,
                        "features": f,
                    }
                    fh.write(json.dumps(rec) + "\n")
                    n_rows += 1
    print(f"{n_mod} teacher modules, {n_rows} entities -> {out}")


if __name__ == "__main__":
    main()
