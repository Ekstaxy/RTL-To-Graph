"""Carry session answers over to a new plan after a frontend change.

A frontend fix changes the entity table (fanout, auto roles) of the affected modules, hence their
prompt and unit hash, but not their entity IDs (ordered by source position). An earlier answer for
the same (design, module) is therefore copied to the new custom_id; ingest-session then
re-validates it against the NEW table, and anything that no longer validates is re-annotated.

    python experiments/e2_session_annotation/rekey.py runs/batches/plan_NEW.json
    -> copies answers into the plan's units_dir, prints the CIDs still missing
"""

import json
import shutil
import sys
from pathlib import Path

L1 = Path(__file__).resolve().parents[2]


def main(plan_path: str) -> None:
    new = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    ud = Path(new["units_dir"])
    if not ud.is_absolute():
        ud = L1 / ud
    index: dict[tuple, Path] = {}
    for pf in sorted((L1 / "runs/batches").glob("plan_*.json")):
        if pf.resolve() == Path(plan_path).resolve():
            continue
        meta = json.loads(pf.read_text(encoding="utf-8"))
        d = meta.get("units_dir")
        if not d:
            continue
        d = Path(d) if Path(d).is_absolute() else L1 / d
        for u in meta["units"]:
            f = d / f"{u['custom_id']}.answer.json"
            if f.exists():
                index[(u["design"]["name"], u["module"])] = f  # later plans win
    # fallback: the latest final answer in the Run Store for the same (design, module, model)
    store: dict[tuple, dict] = {}
    sp = L1 / "runs/store/runs.jsonl"
    if sp.exists():
        for line in sp.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            parsed = (r.get("response") or {}).get("parsed")
            q = r["request"]
            if parsed is None or r.get("validation", {}).get("errors") or q.get("k_index", 0):
                continue
            if q.get("model") != new.get("model"):
                continue
            store[(r["design"]["name"], r["module"])] = parsed
    kept = copied = from_store = 0
    missing = []
    for u in new["units"]:
        dst = ud / f"{u['custom_id']}.answer.json"
        if dst.exists():
            kept += 1
            continue
        src = index.get((u["design"]["name"], u["module"]))
        if src is not None:
            shutil.copy(src, dst)
            copied += 1
        elif (u["design"]["name"], u["module"]) in store:
            ans = store[(u["design"]["name"], u["module"])]
            dst.write_text(json.dumps(ans, ensure_ascii=False, indent=1), encoding="utf-8")
            from_store += 1
        else:
            missing.append(u["custom_id"])
    print(
        json.dumps(
            {"kept": kept, "copied": copied, "from_store": from_store, "missing": len(missing)}
        )
    )
    (ud / "_missing.json").write_text(json.dumps(missing), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
