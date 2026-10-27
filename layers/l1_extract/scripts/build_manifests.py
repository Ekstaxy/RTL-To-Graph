"""Build corpus manifests for the spec->RTL datasets (RTLLM, VerilogEval spec-to-rtl).

Each entry carries "spec": path to the natural-language spec. The spec is *privileged*
teacher-side information (SPEC §7.4); the student never sees it.
"""

import json
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "data/corpus")

rtllm = []
for v in sorted((root / "RTLLM").rglob("verified_*.v")):
    if any(p.startswith("_") for p in v.parts):
        continue
    d = v.parent
    spec = d / "design_description.txt"
    rtllm.append(
        {
            "name": "rtllm_" + d.name,
            "files": [str(v.relative_to(root)).replace("\\", "/")],
            "top": None,
            "spec": str(spec.relative_to(root)).replace("\\", "/") if spec.exists() else None,
            "group": v.parts[-4] if len(v.parts) >= 4 else "",
        }
    )
(root / "rtllm.json").write_text(json.dumps(rtllm, indent=1), encoding="utf-8")

ve = []
for ref in sorted((root / "verilog-eval" / "dataset_spec-to-rtl").glob("Prob*_ref.sv")):
    stem = ref.name[: -len("_ref.sv")]
    spec = ref.with_name(stem + "_prompt.txt")
    ve.append(
        {
            "name": "ve_" + stem,
            "files": [str(ref.relative_to(root)).replace("\\", "/")],
            "top": "RefModule",
            "spec": str(spec.relative_to(root)).replace("\\", "/") if spec.exists() else None,
        }
    )
(root / "verilog_eval.json").write_text(json.dumps(ve, indent=1), encoding="utf-8")
print(f"rtllm: {len(rtllm)} designs, verilog-eval: {len(ve)} problems")
