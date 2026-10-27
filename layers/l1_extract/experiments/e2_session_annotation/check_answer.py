"""Validate a session annotator's answer file (same checks the API path runs before retry/refine).

usage: python experiments/e2_session_annotation/check_answer.py
           experiments/e2_session_annotation/session/w1/<custom_id>.answer.json
"""

import glob
import json
import re
import sys
from pathlib import Path

from rtl2d_l1.frontend.entities import EntityTable
from rtl2d_l1.llm.teacher import parse_annotation
from rtl2d_l1.schema import EntityTableModel
from rtl2d_l1.taxonomy import Level
from rtl2d_l1.validate import validate


def find_unit(cid: str) -> dict:
    for p in sorted(glob.glob("runs/batches/plan_*.json")):
        for u in json.loads(Path(p).read_text(encoding="utf-8"))["units"]:
            if u["custom_id"] == cid:
                return u
    sys.exit(f"unit {cid} not found in runs/batches/plan_*.json")


def main() -> None:
    ans = Path(sys.argv[1])
    cid = re.sub(
        r"\.(answer|pass\d+)\.json$", "", ans.name
    )  # works for CID.answer.json and CID.passN.json
    u = find_unit(cid)
    tm = EntityTableModel.model_validate(u["table"])
    t = EntityTable(
        design=tm.design,
        module=tm.module,
        canonical_instance=tm.canonical_instance,
        file=tm.file,
        line_start=tm.line_start,
        line_end=tm.line_end,
        rows=tm.rows,
    )
    ann, err = parse_annotation(ans.read_text(encoding="utf-8"))
    if err:
        print("ERROR", err)
        sys.exit(1)
    rep = validate(ann, t, Level.LOW)
    for e in rep.errors:
        print("ERROR", e)
    for w in rep.warnings:
        print("WARN ", w)
    ports = {r.id for r in t.rows if r.kind.startswith("port_")}
    covered = {x for i in ann.interfaces for x in i.member_ids}
    if ports - covered:
        print(
            "WARN  ports missing from interfaces:",
            sorted(ports - covered, key=lambda x: int(x[1:])),
        )
    print(
        "OK" if rep.ok else "FAILED",
        f"anchors={len(ann.anchors)} groups={len(ann.groups)} interfaces={len(ann.interfaces)}",
    )
    sys.exit(0 if rep.ok else 1)


if __name__ == "__main__":
    main()
