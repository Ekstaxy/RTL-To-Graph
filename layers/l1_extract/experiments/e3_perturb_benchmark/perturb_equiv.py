"""Run the equivalence checker over the perturbation benchmark.

python experiments/e3_perturb_benchmark/perturb_equiv.py
    every data/<design>/<style>/ rewrite vs its original
python experiments/e3_perturb_benchmark/perturb_equiv.py --self
    each original vs itself (Yosys parse + checker smoke test)
"""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # layers/l1_extract
P = Path(__file__).resolve().parent / "data"
designs = json.loads((P / "designs.json").read_text(encoding="utf-8"))


def check(x, gate_files, depth=12):
    p = [f"{k}={v}" for k, v in x["params"].items()]
    cmd = [
        sys.executable,
        str(ROOT / "scripts/equiv_check.py"),
        "--gold",
        *[str(ROOT / f) for f in x["files"]],
        "--gate",
        *[str(f) for f in gate_files],
        "--top",
        x["top"],
        "--reset",
        x["reset"],
        "--depth",
        str(depth),
        "--reset-active",
        x["reset_active"],
    ]
    if p:
        cmd += ["--param", *p]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    out = (r.stdout + r.stderr).strip().splitlines()
    return out[0] if out else f"rc={r.returncode}"


jobs = []
if "--self" in sys.argv:
    jobs = [(x, "self", [ROOT / f for f in x["files"]]) for x in designs]
else:
    for x in designs:
        for style in ("S1", "S2"):
            d = P / x["name"] / style
            files = (
                sorted(f for f in d.glob("*") if f.suffix in (".v", ".sv")) if d.exists() else []
            )
            if files:
                jobs.append((x, style, files))
with ThreadPoolExecutor(max_workers=8) as ex:
    results = list(ex.map(lambda j: (j[0]["name"], j[1], check(j[0], j[2])), jobs))
summary = {}
for name, style, res in results:
    print(f"{name:20s} {style:5s} {res}")
    summary[f"{name}/{style}"] = res
if "--self" not in sys.argv:
    (P / "equiv_results.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
