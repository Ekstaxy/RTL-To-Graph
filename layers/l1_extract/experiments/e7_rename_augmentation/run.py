"""Rename augmentation -> extra SFT samples, with no annotation cost.

For every leaf module the teacher annotated (Run Store, model claude-session):
  1. write renamed variants (internal names, enum literals, localparams; for design tops also
     ports, parameters and the module name), comments stripped;
  2. re-elaborate and rebuild the entity table: entity IDs must be identical;
  3. transfer the teacher's final annotation: same IDs, renamed `name`, and every free-text field
     (why / module_summary / group names) rewritten with the same mapping;
  4. keep the sample only if it passes the validator with evidence checking (no errors).

    python experiments/e7_rename_augmentation/run.py MANIFEST... [--seeds 0 1 2] \
        [--out runs/sft_aug.jsonl]
"""

import argparse
import json
import re
from pathlib import Path

from rtl2d_l1.augment import rename_variant
from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate
from rtl2d_l1.llm.prompt import SYSTEM_PROMPT, unit_hash, user_message
from rtl2d_l1.llm.teacher import TeacherConfig
from rtl2d_l1.pipeline import ANN_LEVEL, RunConfig, _privileged_hash, annotate_design
from rtl2d_l1.schema import ModuleAnnotation
from rtl2d_l1.store import RunStore
from rtl2d_l1.validate import validate

L1 = Path(__file__).resolve().parents[2]
MODEL, EFFORT = "claude-session", "session"


def designs(manifest: Path):
    for it in json.loads(manifest.read_text(encoding="utf-8")):
        yield {
            "name": it.get("name") or it["top"],
            "files": [str(manifest.parent / f) for f in it["files"]],
            "top": it.get("top"),
            "include_dirs": [str(manifest.parent / d) for d in it.get("include_dirs", [])],
            "defines": it.get("defines", []),
            "spec": str(manifest.parent / it["spec"]) if it.get("spec") else None,
        }


def rewrite_text(s: str, mapping: dict[str, str]) -> str:
    if not s or not mapping:
        return s
    pat = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)) + r")\b"
    )
    return pat.sub(lambda m: mapping[m.group(1)], s)


def transfer(ann: dict, mapping: dict[str, str]) -> dict:
    def ren(nm):
        parts = nm.split(".")
        parts[-1] = mapping.get(parts[-1], parts[-1])
        return ".".join(parts)

    out = dict(ann)
    out["module_summary"] = rewrite_text(ann.get("module_summary", ""), mapping)
    out["anchors"] = [
        dict(a, name=ren(a["name"]), why=rewrite_text(a.get("why", ""), mapping))
        for a in ann.get("anchors", [])
    ]
    out["groups"] = [
        dict(
            g,
            name=rewrite_text(g["name"], mapping),
            description=rewrite_text(g.get("description", ""), mapping),
        )
        for g in ann.get("groups", [])
    ]
    out["interfaces"] = [
        dict(i, name=rewrite_text(i["name"], mapping)) for i in ann.get("interfaces", [])
    ]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifests", nargs="+")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--out", default="runs/sft_aug.jsonl")
    a = ap.parse_args()
    store = RunStore(L1 / "runs/store")
    cfg = RunConfig(
        mode="teacher",
        store_only=True,
        refine=False,
        teacher=TeacherConfig(model=MODEL, effort=EFFORT),
    )
    work = L1 / "runs/e7"
    seen_units: set[str] = set()
    stats = {
        "leaf_units": 0,
        "written": 0,
        "id_mismatch": 0,
        "invalid": 0,
        "no_record": 0,
        "error": 0,
    }
    out = L1 / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for m in a.manifests:
            for d in designs(Path(m).resolve()):
                spec = (
                    Path(d["spec"]).read_text(encoding="utf-8", errors="replace")
                    if d["spec"]
                    else None
                )
                try:
                    run = annotate_design(
                        d["files"],
                        top=d["top"],
                        include_dirs=d["include_dirs"],
                        defines=d["defines"],
                        cfg=cfg,
                        store=store,
                        name=d["name"],
                        spec=spec,
                    )
                except Exception:
                    stats["error"] += 1
                    continue
                tops = {t.name for t in run.design.tops}
                for t in run.tables:
                    res = run.results_full.get(t.module)
                    if res is None or res.source != "teacher" or t.children:
                        continue
                    um = user_message(t, ANN_LEVEL, {})
                    uh = unit_hash(um + _privileged_hash(spec), MODEL, EFFORT)
                    if uh in seen_units:
                        continue
                    seen_units.add(uh)
                    rec = store.lookup(uh, 0)
                    if rec is None or rec.response.get("parsed") is None:
                        stats["no_record"] += 1
                        continue
                    stats["leaf_units"] += 1
                    standalone = t.module in tops and len(run.tables) == 1
                    for seed in a.seeds:
                        try:
                            v = rename_variant(
                                t, work / f"{uh[:16]}_s{seed}", include_ports=standalone, seed=seed
                            )
                            files = [
                                str(v.path) if Path(f).resolve() == Path(t.file).resolve() else f
                                for f in d["files"]
                            ]
                            G2 = build_graph(
                                elaborate(
                                    files,
                                    top=v.top or d["top"],
                                    include_dirs=d["include_dirs"],
                                    defines=d["defines"],
                                )
                            )
                            mod2 = v.top if (standalone and v.top) else t.module
                            t2 = {x.module: x for x in build_entity_tables(G2)}.get(mod2)
                        except Exception:
                            stats["error"] += 1
                            continue
                        if t2 is None or [r.id for r in t2.rows] != [r.id for r in t.rows]:
                            stats["id_mismatch"] += 1
                            continue
                        ann = transfer(rec.response["parsed"], v.mapping)
                        rep = validate(
                            ModuleAnnotation.model_validate(ann),
                            t2,
                            ANN_LEVEL,
                            require_evidence=True,
                        )
                        if rep.errors:
                            stats["invalid"] += 1
                            continue
                        fh.write(
                            json.dumps(
                                {
                                    "messages": [
                                        {"role": "system", "content": SYSTEM_PROMPT},
                                        {
                                            "role": "user",
                                            "content": user_message(t2, ANN_LEVEL, {}),
                                        },
                                        {
                                            "role": "assistant",
                                            "content": json.dumps(ann, ensure_ascii=False),
                                        },
                                    ],
                                    "meta": {
                                        "source": "augment-rename",
                                        "seed": seed,
                                        "orig_unit_hash": uh,
                                        "orig_run_id": rec.run_id,
                                        "module": mod2,
                                        "design": d["name"],
                                        "ports_renamed": standalone,
                                    },
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                        stats["written"] += 1
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
