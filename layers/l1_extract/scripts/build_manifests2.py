"""Manifests for the extra open-source corpora (verilog-axis, verilog-uart, serv, darkriscv)."""

import json
import re
from pathlib import Path

root = Path("data/corpus")


def modules_in(f: Path) -> list[str]:
    return re.findall(r"^\s*module\s+(\w+)", f.read_text(encoding="utf-8", errors="replace"), re.M)


out = {}
for repo in ("verilog-axis", "verilog-uart"):
    files = sorted((root / repo / "rtl").glob("*.v"))
    rel = [str(f.relative_to(root)).replace("\\", "/") for f in files]
    items = []
    for f in files:
        for m in modules_in(f):
            items.append({"name": f"{repo}_{m}", "files": rel, "top": m, "group": repo})
    out[repo] = items
serv = sorted((root / "serv" / "rtl").glob("*.v"))
srel = [str(f.relative_to(root)).replace("\\", "/") for f in serv]
out["serv"] = [
    {"name": f"serv_{t}", "files": srel, "top": t}
    for t in (
        "serv_rf_top",
        "serv_top",
        "serv_state",
        "serv_decode",
        "serv_ctrl",
        "serv_alu",
        "serv_bufreg",
        "serv_csr",
        "serv_mem_if",
    )
]
dark = [f for f in sorted((root / "darkriscv" / "rtl").glob("*.v"))]
drel = [str(f.relative_to(root)).replace("\\", "/") for f in dark]
out["darkriscv"] = [
    {"name": f"dark_{t}", "files": drel, "top": t, "include_dirs": ["darkriscv/rtl"]}
    for t in ("darkriscv", "darksocv", "darkuart", "darkcache")
]
allitems = [x for v in out.values() for x in v]
(root / "opensource.json").write_text(json.dumps(allitems, indent=1), encoding="utf-8")
print({k: len(v) for k, v in out.items()}, "total", len(allitems))
