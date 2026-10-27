"""Package L1 teacher-mode outputs for downstream layers (L2 block partitioning).

    python scripts/export_teacher_outputs.py runs/teacher_out outputs/teacher-v1

Per design it writes blocks.json and copies fsm.json + Mermaid; anchors.json (MEDIUM view),
anchors_full.json (all tiers) and the entity tables of all designs go into raw.tar.gz.
blocks.json: every group of every module resolved to names, with child instances
(instance name -> module) and evidence lines, plus the anchors no group covers.
An index.json lists all designs with their tops, block counts and how many modules were
annotated by the teacher vs. filled in by the heuristic (trivial modules).
"""

import json
import shutil
import sys
from pathlib import Path

L1 = Path(__file__).resolve().parents[1]


def _rel(v):
    """Absolute paths under layers/l1_extract -> repo-relative POSIX paths (portable, and no user
    directories in the published files)."""
    if isinstance(v, str) and (v[1:3] == ":\\" or v[1:3] == ":/" or v.startswith("/")):
        try:
            rel = Path(v).resolve().relative_to(L1).as_posix()
            # third-party sources are published as a snapshot under data/rtl/ (same layout)
            return (
                "data/rtl/" + rel[len("data/corpus/") :] if rel.startswith("data/corpus/") else rel
            )
        except (ValueError, OSError):
            return v
    if isinstance(v, dict):
        return {k: _rel(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_rel(x) for x in v]
    return v


def _copy_json(src: Path, dst: Path) -> None:
    data = _rel(json.loads(src.read_text(encoding="utf-8")))
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _entities(design_dir: Path) -> dict[str, dict]:
    out = {}
    for f in (design_dir / "entities").glob("*.json"):
        t = json.loads(f.read_text(encoding="utf-8"))
        out[t["module"]] = t
    return out


def _anchor_view(a: dict) -> dict:
    keep = ("id", "name", "role", "importance", "score", "struct_score", "trace", "why", "lines")
    return {k: a.get(k) for k in keep}


def blocks_for(design_dir: Path) -> dict:
    full = json.loads((design_dir / "anchors_full.json").read_text(encoding="utf-8"))
    ents = _entities(design_dir)
    mods = {}
    for mod, res in full["modules"].items():
        t = ents.get(mod, {"rows": [], "file": None, "line_start": None, "line_end": None})
        rows = {r["id"]: r for r in t["rows"]}
        anchors = {a["id"]: a for a in res["anchors"]}

        def member(i, rows=rows):
            r = rows.get(i, {})
            if r.get("kind") == "inst":
                return {"id": i, "instance": r.get("name"), "module": r.get("definition")}
            return {"id": i, "name": r.get("name"), "kind": r.get("kind")}

        grouped, blocks = set(), []
        for g in res["groups"]:
            grouped |= set(g["anchor_ids"])
            ms = [member(i) for i in g.get("member_ids", [])]
            blocks.append(
                {
                    "name": g["name"],
                    "kind": g["kind"],
                    "description": g.get("description", ""),
                    "anchors": [_anchor_view(anchors[i]) for i in g["anchor_ids"] if i in anchors],
                    "instances": [m for m in ms if "instance" in m],
                    "members": [m for m in ms if "instance" not in m],
                }
            )
        insts = [
            {"id": r["id"], "instance": r["name"], "module": r["definition"]}
            for r in t["rows"]
            if r["kind"] == "inst"
        ]
        in_block = {m["id"] for b in blocks for m in b["instances"]}
        mods[mod] = {
            "source": res["source"],  # teacher | heuristic (trivial module, no LLM call)
            "canonical_instance": res["canonical_instance"],
            "file": t.get("file"),
            "lines": [t.get("line_start"), t.get("line_end")],
            "summary": res.get("module_summary", ""),
            "blocks": blocks,
            "ungrouped_anchors": [_anchor_view(a) for i, a in anchors.items() if i not in grouped],
            "instances_not_in_a_block": [x for x in insts if x["id"] not in in_block],
            "interfaces": [
                dict(i, members=[member(m) for m in i["member_ids"]]) for i in res["interfaces"]
            ],
        }
    return {
        "schema": "l1-blocks-v1",
        "design": full["design"],
        "tops": full["tops"],
        "taxonomy_version": full["taxonomy_version"],
        "modules": mods,
    }


def main(src: str, dst: str) -> None:
    src_p, dst_p = Path(src), Path(dst)
    dst_p.mkdir(parents=True, exist_ok=True)
    index = []
    for d in sorted(p for p in src_p.iterdir() if (p / "anchors_full.json").exists()):
        out = dst_p / d.name
        out.mkdir(exist_ok=True)
        for f in ("anchors.json", "anchors_full.json", "fsm.json"):
            if (d / f).exists():
                _copy_json(d / f, out / f)
        if (d / "fsm").exists():
            shutil.copytree(d / "fsm", out / "fsm", dirs_exist_ok=True)
        if (d / "entities").exists():
            (out / "entities").mkdir(exist_ok=True)
            for f in (d / "entities").glob("*.json"):
                _copy_json(f, out / "entities" / f.name)
        b = _rel(blocks_for(d))
        (out / "blocks.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), "utf-8")
        srcs = [m["source"] for m in b["modules"].values()]
        index.append(
            {
                "design": d.name,
                "tops": b["tops"],
                "modules": len(srcs),
                "teacher_modules": srcs.count("teacher"),
                "heuristic_modules": srcs.count("heuristic"),
                "blocks": sum(len(m["blocks"]) for m in b["modules"].values()),
            }
        )
    (dst_p / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    # raw files (anchors views + entity tables) go into one archive; blocks/fsm stay plain JSON
    import tarfile

    with tarfile.open(dst_p / "raw.tar.gz", "w:gz") as tar:
        for d in sorted(p for p in dst_p.iterdir() if p.is_dir()):
            for name in ("anchors.json", "anchors_full.json", "entities"):
                if (d / name).exists():
                    tar.add(d / name, arcname=f"{d.name}/{name}")
                    if (d / name).is_dir():
                        shutil.rmtree(d / name)
                    else:
                        (d / name).unlink()
    n_t = sum(x["teacher_modules"] for x in index)
    n_h = sum(x["heuristic_modules"] for x in index)
    print(f"{len(index)} designs, module results: teacher {n_t}, heuristic {n_h}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
