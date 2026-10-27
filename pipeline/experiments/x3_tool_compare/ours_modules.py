"""Draw ours for x3's module-level set: x2's own L1 -> teacher-v1 -> bridge -> e3 path, run on
designs x2 did not include (leaf modules), into runs/x3_tool_compare/ours_modules/.

x2's run.py is loaded as a module and only its output directory and design lookup are swapped;
no x2 output and no layer source changes.

    uv run --package rtl2d-l1 --with nodejs-wheel --with ortools python \\
        pipeline/experiments/x3_tool_compare/ours_modules.py [--engines elk,busbar]
Output: runs/x3_tool_compare/ours_modules/{inputs/,svg/,png/,stages.json,results.json}
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
L1 = ROOT / "layers" / "l1_extract"
OUT = ROOT / "runs" / "x3_tool_compare" / "ours_modules"


def load_x2():
    spec = importlib.util.spec_from_file_location(
        "x2run", ROOT / "pipeline" / "experiments" / "x2_l1_to_paper" / "run.py")
    x2 = importlib.util.module_from_spec(spec)
    sys.modules["x2run"] = x2
    spec.loader.exec_module(x2)
    return x2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default="elk,busbar")
    a = ap.parse_args()
    designs = json.loads((HERE / "designs_module.json").read_text())["designs"]
    x2 = load_x2()
    x2.OUT = OUT
    # same shape as x1's eval_set entries; data/rtl holds the same files as data/corpus
    entries = {d["x2"]: {"name": d["x2"], "category": "leaf", "split": "test", "top": d["top"],
                         "files": [str(L1 / "data" / "rtl" / f) for f in d["files"]]}
               for d in designs}
    x2.eval_entry = entries.__getitem__
    OUT.mkdir(parents=True, exist_ok=True)
    stages, rows = [], []
    for name in entries:
        try:
            s = x2.bridge_one(name)
        except Exception as e:  # noqa: BLE001 - recorded as the result
            s = {"design": name, "error": f"{type(e).__name__}: {str(e)[:300]}"}
        stages.append(s)
        print(json.dumps(s, ensure_ascii=False)[:300], flush=True)
        if "error" in s:
            continue
        for eng in a.engines.split(","):
            r = x2.draw_one({"input": name, "engine": eng, "cpsat_seconds": 20.0})
            rows.append(r)
            print(f"  {name:28} {eng:7} {r['status']:6} {r.get('score', r.get('error', ''))}",
                  flush=True)
    (OUT / "stages.json").write_text(json.dumps(stages, indent=1, ensure_ascii=False))
    (OUT / "results.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
