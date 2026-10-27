"""Teacher labels without the Run Store: read L1's committed teacher-v1 archive.

`layers/l1_extract/outputs/teacher-v1/raw.tar.gz` holds, per design, `anchors_full.json`:
L1's own `AnchorsFile` (one `ModuleResult` per module, every tier) as the teacher produced
it. L1's front end runs here as usual (heuristic mode, no API, no store); then each module
result is replaced by the archived teacher result, after checking that every anchor and
group member ID the teacher used exists in today's entity table (IDs are stable per
ENTITIES_VERSION; a mismatch keeps the heuristic result and is reported).
"""

from __future__ import annotations

import json
import tarfile
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
L1 = ROOT / "layers" / "l1_extract"
ARCHIVE = L1 / "outputs" / "teacher-v1" / "raw.tar.gz"


@cache
def _members() -> dict[str, str]:
    with tarfile.open(ARCHIVE) as tf:
        return {m.name.split("/")[0]: m.name for m in tf.getmembers()
                if m.name.endswith("/anchors_full.json")}


def load(design: str) -> dict | None:
    name = _members().get(design)
    if name is None:
        return None
    with tarfile.open(ARCHIVE) as tf:
        return json.load(tf.extractfile(name))


def patched_annotate(design: str, report: list[str]):
    """An `annotate_design` replacement for x1's bridge: heuristic front end + teacher-v1."""
    from rtl2d_l1.pipeline import RunConfig, annotate_design
    from rtl2d_l1.schema import ModuleResult

    archived = load(design)

    def annotate(files, *, top=None, cfg=None, store=None, **kw):  # noqa: ARG001
        run = annotate_design(files, top=top, cfg=RunConfig(mode="heuristic"), **kw)
        if archived is None:
            report.append(f"{design}: not in teacher-v1, heuristic labels")
            return run
        tables = run.tables_by_module
        for mod, raw in archived["modules"].items():
            if mod not in tables or raw.get("source") != "teacher":
                continue
            ids = {r.id for r in tables[mod].rows}
            used = {a["id"] for a in raw.get("anchors", [])}
            for g in raw.get("groups", []):
                used |= set(g.get("member_ids", []))
            for i in raw.get("interfaces", []):
                used |= set(i.get("member_ids", []))
            missing = used - ids
            if missing:
                report.append(f"{design}/{mod}: {len(missing)} teacher IDs not in entity table, "
                              f"heuristic kept")
                continue
            res = ModuleResult.model_validate(raw)
            run.results_full[mod] = res
            run.results[mod] = res
        return run

    return annotate
