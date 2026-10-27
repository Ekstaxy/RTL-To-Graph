"""Fit and evaluate the quantified importance score (grouped cross-validation).

    uv run --with numpy --with scikit-learn python experiments/e5_importance_score/fit.py

Setting: the annotator (any LLM) only selects anchors and roles; the score decides importance.
Targets, among anchored entities: HIGH = critical, MEDIUM = critical or major.
Feature sets: S = structure only, SR = structure + role, SRT = structure + role + LLM tier.
"""

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from rtl2d_l1.importance import STRUCT_FEATURES  # noqa: E402
from rtl2d_l1.taxonomy import Role  # noqa: E402

L1 = Path(__file__).resolve().parents[2]
ROLES = [r.value for r in Role]
TIERS = ["critical", "major", "minor"]


def load(path):
    """Rows of the dataset; a module that occurs in several designs is kept once and grouped by
    module name, so cross-validation never sees the same module on both sides."""
    out, seen = [], set()
    for x in open(path, encoding="utf-8"):
        r = json.loads(x)
        if r["manifest"].endswith("round4_all.json"):
            r["group"] = r["module"]
            key = (r["module"], r["id"], r["name"])
            if key in seen:
                continue
            seen.add(key)
        out.append(r)
    return out


def matrix(rows, use_role, use_tier):
    X = []
    for r in rows:
        v = [r["features"][f] for f in STRUCT_FEATURES]
        if use_role:
            v += [float(r["role"] == x) for x in ROLES]
        if use_tier:
            v += [float(r["tier"] == x) for x in TIERS]
        X.append(v)
    return np.array(X)


def cv_probs(X, y, groups, C=1.0, folds=10):
    p = np.zeros(len(y))
    for tr, te in GroupKFold(n_splits=folds).split(X, y, groups):
        m = LogisticRegression(C=C, max_iter=5000)
        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
        m.fit((X[tr] - mu) / sd, y[tr])
        p[te] = m.predict_proba((X[te] - mu) / sd)[:, 1]
    return p


def main():
    data = (
        sys.argv[sys.argv.index("--data") + 1] if "--data" in sys.argv else "runs/e5/dataset.jsonl"
    )
    out_tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else ""
    rows = load(L1 / data)
    anch = [r for r in rows if r["tier"] != "none"]
    groups_all = np.array([r["group"] for r in rows])
    groups = np.array([r["group"] for r in anch])
    report = {"n_entities": len(rows), "n_anchors": len(anch), "n_groups": len(set(groups))}

    # selection: can structure alone tell which entities the teacher anchors at all?
    y_sel = np.array([r["tier"] != "none" for r in rows], dtype=int)
    p = cv_probs(matrix(rows, False, False), y_sel, groups_all)
    report["AUC_selection_S"] = round(roc_auc_score(y_sel, p), 3)

    for target, pos in (("MEDIUM", {"critical", "major"}), ("HIGH", {"critical"})):
        y = np.array([r["tier"] in pos for r in anch], dtype=int)
        for tag, ur in (("S", False), ("SR", True)):
            p = cv_probs(matrix(anch, ur, False), y, groups)
            report[f"AUC_{target}_{tag}"] = round(roc_auc_score(y, p), 3)
            report[f"brier_{target}_{tag}"] = round(float(np.mean((p - y) ** 2)), 4)
        report[f"base_rate_{target}"] = round(float(y.mean()), 3)

    # final coefficients on all data (structure + role), for the frozen score
    coefs = {}
    for target, pos in (("MEDIUM", {"critical", "major"}), ("HIGH", {"critical"})):
        X = matrix(anch, True, False)
        y = np.array([r["tier"] in pos for r in anch], dtype=int)
        mu, sd = X.mean(0), X.std(0) + 1e-9
        m = LogisticRegression(C=1.0, max_iter=5000).fit((X - mu) / sd, y)
        names = STRUCT_FEATURES + [f"role:{x}" for x in ROLES]
        w = m.coef_[0] / sd
        b = float(m.intercept_[0] - (m.coef_[0] * mu / sd).sum())
        coefs[target] = {
            "bias": round(b, 5),
            **{n: round(float(v), 5) for n, v in zip(names, w, strict=True)},
        }
    out = L1 / "runs/e5"
    (out / f"report{out_tag}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    (out / f"coefs{out_tag}.json").write_text(json.dumps(coefs, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
