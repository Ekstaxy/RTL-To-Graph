"""Weak annotator vs Opus-level annotator on the same units (same entity IDs).

    python experiments/e6_weak_annotator/compare.py [--weak claude-haiku-session]

For every module annotated by both, per level and importance mode (tier / score / structure):
  * recall    : strong-annotator view anchors also in the weak annotator's view
  * precision : weak view anchors also in the strong view
  * role      : role agreement on anchors both selected (any level)
Strong = claude-session (Opus-level session teacher, the reference used everywhere else).
"""

import json
import statistics as st
import sys
from pathlib import Path

from rtl2d_l1.controls import Controls, apply_view
from rtl2d_l1.llm.teacher import TeacherConfig
from rtl2d_l1.pipeline import RunConfig, annotate_design
from rtl2d_l1.store import RunStore
from rtl2d_l1.taxonomy import Level

L1 = Path(__file__).resolve().parents[2]
E = Path(__file__).resolve().parent
WEAK = sys.argv[sys.argv.index("--weak") + 1] if "--weak" in sys.argv else "claude-haiku-session"
MODES = ("tier", "score", "structure")
# --fixed-ref: compare every weak mode against the strong annotator's default ("score") view
FIXED_REF = "--fixed-ref" in sys.argv


def results(d, model):
    cfg = RunConfig(
        mode="teacher",
        store_only=True,
        refine=False,
        teacher=TeacherConfig(model=model, effort="session"),
    )
    run = annotate_design(d["files"], top=d["top"], cfg=cfg, store=RunStore(L1 / "runs/store"))
    return run


def main():
    designs = json.loads((E / "manifest.json").read_text(encoding="utf-8"))
    acc = {(m, lv): {"recall": [], "precision": []} for m in MODES for lv in Level}
    roles, n_mod, missing = [], 0, []
    sizes = {(m, lv, w): [] for m in MODES for lv in Level for w in ("strong", "weak")}
    for it in designs:
        d = {"files": [str(E / f) for f in it["files"]], "top": it["top"]}
        rs, rw = results(d, "claude-session"), results(d, WEAK)
        tb = rs.tables_by_module
        for mod, a in rs.results_full.items():
            b = rw.results_full.get(mod)
            if a.source != "teacher":
                continue
            if b is None or b.source != "teacher":
                missing.append(f"{it['name']}:{mod}")
                continue
            n_mod += 1
            ra = {x.id: x.role for x in a.anchors}
            rb = {x.id: x.role for x in b.anchors}
            roles += [ra[i] == rb[i] for i in ra.keys() & rb.keys()]
            for m in MODES:
                for lv in Level:
                    c = Controls(level=lv, importance=m)
                    # reference: the strong annotator's DEFAULT output ("score" mode)
                    cref = Controls(level=lv, importance="score") if FIXED_REF else c
                    sa = {x.id for x in apply_view(a, cref, tb.get(mod)).anchors}
                    sb = {x.id for x in apply_view(b, c, tb.get(mod)).anchors}
                    sizes[(m, lv, "strong")].append(len(sa))
                    sizes[(m, lv, "weak")].append(len(sb))
                    if sa:
                        acc[(m, lv)]["recall"].append(len(sa & sb) / len(sa))
                    if sb:
                        acc[(m, lv)]["precision"].append(len(sa & sb) / len(sb))
    rep = {
        "weak_model": WEAK,
        "reference": "strong score view" if FIXED_REF else "strong view in the same mode",
        "modules_compared": n_mod,
        "modules_missing_weak": missing,
        "role_agreement": round(sum(roles) / len(roles), 3) if roles else None,
    }
    for (m, lv), v in acc.items():
        r = st.mean(v["recall"]) if v["recall"] else 0.0
        p = st.mean(v["precision"]) if v["precision"] else 0.0
        rep[f"{m}/{lv.value}"] = {
            "recall": round(r, 3),
            "precision": round(p, 3),
            "F1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "median_size_strong": st.median(sizes[(m, lv, "strong")]),
            "median_size_weak": st.median(sizes[(m, lv, "weak")]),
        }
    out = L1 / "runs/e6"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"compare_{WEAK}{'_fixedref' if FIXED_REF else ''}.json").write_text(
        json.dumps(rep, indent=1), encoding="utf-8"
    )
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
