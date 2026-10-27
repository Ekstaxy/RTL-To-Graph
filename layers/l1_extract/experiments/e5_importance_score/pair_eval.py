"""Is the score as good as a second annotator?

For every unit annotated independently twice (k0 / k1) in the Run Store, predict annotator A's
importance from what annotator B produced:
  * annotator baseline: B's tier (critical > major > minor) as the ranking;
  * score: structure + B's role, model trained WITHOUT any circuit that appears in the pairs.
Evaluated on entities both annotators anchored (both directions A<-B and B<-A).

    uv run --with numpy --with scikit-learn python experiments/e5_importance_score/pair_eval.py
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

L1 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(L1 / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fit import ROLES, matrix  # noqa: E402

from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate  # noqa: E402
from rtl2d_l1.importance import module_features  # noqa: E402

TIER_RANK = {"critical": 2, "major": 1, "minor": 0}
TIER_VALUE = {2: 100.0, 1: 60.0, 0: 20.0}


def local_path(p: str) -> str:
    p = p.replace("\\", "/")
    for marker, new in (("/examples/", L1 / "examples"), ("/data/corpus/", L1 / "data/corpus")):
        if marker in p:
            return str(new / p.split(marker, 1)[1])
    return p


def pairs():
    by = defaultdict(dict)
    for ln in open(L1 / "runs/store/runs.jsonl", encoding="utf-8"):
        r = json.loads(ln)
        if not (r["response"] or {}).get("parsed"):
            continue
        q = r["request"]
        prev = by[r["unit_hash"]].get(q["k_index"])
        if prev is None or q["round"] >= prev["request"]["round"]:
            by[r["unit_hash"]][q["k_index"]] = r
    return [(d[0], d[1]) for d in by.values() if 0 in d and 1 in d]


def main():
    data = [json.loads(x) for x in open(L1 / "runs/e5/dataset.jsonl", encoding="utf-8")]
    P = pairs()
    names = {re.sub(r"^(rtllm_|ve_)", "", a["design"]["name"]) for a, _ in P}
    train = [r for r in data if r["tier"] != "none" and r["group"] not in names]
    models = {}
    for target, pos in (("MEDIUM", {"critical", "major"}), ("HIGH", {"critical"})):
        X = matrix(train, True, False)
        y = np.array([r["tier"] in pos for r in train], dtype=int)
        mu, sd = X.mean(0), X.std(0) + 1e-9
        models[target] = (LogisticRegression(max_iter=5000).fit((X - mu) / sd, y), mu, sd)

    feats_cache = {}
    ys = {"MEDIUM": [], "HIGH": []}
    p_ann, p_score = {"MEDIUM": [], "HIGH": []}, {"MEDIUM": [], "HIGH": []}
    n_both = 0
    for a, b in P:
        key = (tuple(a["design"]["files"]), a["module"])
        if key not in feats_cache:
            files = [local_path(f) for f in a["design"]["files"]]
            G = build_graph(elaborate(files, top=None if len(files) == 1 else a["design"]["name"]))
            t = {x.module: x for x in build_entity_tables(G)}.get(a["module"])
            feats_cache[key] = module_features(G, t) if t else {}
        F = feats_cache[key]
        A = {x["id"]: x for x in a["response"]["parsed"]["anchors"]}
        B = {x["id"]: x for x in b["response"]["parsed"]["anchors"]}
        for X1, X2 in ((A, B), (B, A)):  # predict X1 from X2
            for eid in X1.keys() & X2.keys() & F.keys():
                n_both += 1
                row = {"features": F[eid], "role": X2[eid]["role"], "tier": None}
                for target, pos in (("MEDIUM", {"critical", "major"}), ("HIGH", {"critical"})):
                    m, mu, sd = models[target]
                    ys[target].append(int(X1[eid]["importance"] in pos))
                    p_ann[target].append(TIER_RANK[X2[eid]["importance"]])
                    x = (matrix([row], True, False) - mu) / sd
                    p_score[target].append(m.predict_proba(x)[0, 1])
    rep = {"pairs": len(P), "entity_predictions": n_both, "excluded_groups": sorted(names)}
    # single combined number: s_struct = 50*P(MEDIUM) + 50*P(HIGH); s_tier = 100/60/20
    s_struct = 50 * np.array(p_score["MEDIUM"]) + 50 * np.array(p_score["HIGH"])
    s_tier = np.array([TIER_VALUE[x] for x in p_ann["MEDIUM"]])
    grid = {}
    for w in np.linspace(0, 1, 11):
        s = w * s_struct + (1 - w) * s_tier
        grid[round(float(w), 1)] = round(
            (roc_auc_score(ys["MEDIUM"], s) + roc_auc_score(ys["HIGH"], s)) / 2, 4
        )
    rep["combined_score_mean_AUC_by_struct_weight"] = grid
    for target in ys:
        y = np.array(ys[target])
        rep[f"AUC_{target}_second_annotator_tier"] = round(roc_auc_score(y, p_ann[target]), 3)
        rep[f"AUC_{target}_score_structure+role"] = round(roc_auc_score(y, p_score[target]), 3)
        blend = np.array(p_score[target]) + 0.5 * np.array(p_ann[target])
        rep[f"AUC_{target}_score+tier"] = round(roc_auc_score(y, blend), 3)
    (L1 / "runs/e5/pair_eval.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    _ = ROLES


if __name__ == "__main__":
    main()
