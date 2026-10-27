"""L1 developer command line (run from layers/l1_extract: `python -m rtl2d_l1.cli ...`).

  python -m rtl2d_l1.cli entities  FILES --top T                 print entity tables
  python -m rtl2d_l1.cli run       FILES --top T --mode M        annotate + trace,
                                                                 write runs/out/<design>/
  python -m rtl2d_l1.cli eval      --manifest corpus.json --gold gold --mode M
  python -m rtl2d_l1.cli augment   --manifest corpus.json --gold gold --seeds 0 1 2
  python -m rtl2d_l1.cli batch plan    --manifest corpus.json [--submit]
  python -m rtl2d_l1.cli batch collect runs/batches/<plan>.json
  python -m rtl2d_l1.cli gold-draft runs/out/<design>/anchors.json --gold gold_new
  python -m rtl2d_l1.cli export-sft --out data/sft.jsonl
  python -m rtl2d_l1.cli cost
  python -m rtl2d_l1.cli yosys-check FILES --top T

A manifest is a JSON list of {"name", "files", "top", "include_dirs"?, "defines"?, "filelist"?};
paths are relative to the manifest file.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from .taxonomy import Level


def _designs(args) -> list[dict]:
    if getattr(args, "manifest", None):
        mp = Path(args.manifest)
        base = mp.parent
        items = json.loads(mp.read_text(encoding="utf-8"))
        out = []
        for it in items:
            out.append(
                {
                    "name": it.get("name") or it["top"],
                    "files": [str(base / f) for f in it.get("files", [])],
                    "top": it.get("top"),
                    "include_dirs": [str(base / d) for d in it.get("include_dirs", [])],
                    "defines": it.get("defines", []),
                    "filelist": str(base / it["filelist"]) if it.get("filelist") else None,
                    "spec": str(base / it["spec"]) if it.get("spec") else None,
                }
            )
        return out
    if not args.files:
        sys.exit("give FILES or --manifest")
    return [
        {
            "name": args.name or args.top,
            "files": args.files,
            "top": args.top,
            "include_dirs": args.incdir or [],
            "defines": args.define or [],
            "filelist": args.filelist,
            "spec": None,
        }
    ]


def _add_src(p: argparse.ArgumentParser) -> None:
    p.add_argument("files", nargs="*")
    p.add_argument("--manifest")
    p.add_argument("--top")
    p.add_argument("--name")
    p.add_argument("-f", "--filelist")
    p.add_argument("-I", "--incdir", action="append")
    p.add_argument("-D", "--define", action="append")


def _add_controls(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("view controls (applied after annotation; free to change)")
    g.add_argument(
        "--preset",
        choices=["overview", "standard", "detailed", "control", "datapath"],
        default=None,
    )
    g.add_argument("--level", choices=[lv.value for lv in Level], default=None)
    g.add_argument(
        "--max-anchors", type=int, default=None, help="per-module cap, most important first"
    )
    g.add_argument("--min-confidence", type=float, default=None)
    g.add_argument(
        "--importance",
        choices=["score", "tier", "structure"],
        default=None,
        help="how levels are decided: 0-100 score (default), annotator tier, or structure only",
    )
    g.add_argument("--min-score", type=float, default=None, help="keep anchors with score >= X")
    g.add_argument("--focus", nargs="*", default=None, help="only these roles")
    g.add_argument("--exclude", nargs="*", default=None, help="drop these roles")
    g.add_argument("--hide-interfaces", action="store_true", default=None)
    g.add_argument("--max-groups", type=int, default=None)
    g.add_argument(
        "--region-threshold", type=float, default=None, help="relevance threshold override (0..1)"
    )
    g.add_argument("--depth", type=float, default=None, help="max slice cost")
    g.add_argument("--reg-hops", type=int, default=None, help="register stages a slice may cross")
    g.add_argument(
        "--steiner",
        action="store_true",
        default=None,
        help="also add Steiner connector nodes to the region",
    )
    g.add_argument("--no-ports", action="store_true", default=None)
    g.add_argument("--max-region-nodes", type=int, default=None)
    g.add_argument(
        "--edge-fanin", type=int, default=None, help="arrows kept per destination anchor (0 = all)"
    )
    g.add_argument(
        "--edge-data-max-hops",
        type=int,
        default=None,
        help="drop longer data arrows (0 = keep all)",
    )


def _controls(args):
    from .controls import Controls
    from .taxonomy import Role

    over = {
        "level": Level(args.level) if args.level else None,
        "max_anchors": args.max_anchors,
        "min_confidence": args.min_confidence,
        "importance": args.importance,
        "min_score": args.min_score,
        "include_roles": {Role(r) for r in args.focus} if args.focus else None,
        "exclude_roles": {Role(r) for r in args.exclude} if args.exclude else None,
        "hide_interfaces": args.hide_interfaces,
        "max_groups": args.max_groups,
        "threshold": args.region_threshold,
        "depth": args.depth,
        "reg_hops": args.reg_hops,
        "steiner": True if args.steiner else None,
        "include_ports": False if args.no_ports else None,
        "max_region_nodes": args.max_region_nodes,
    }
    over = {k: v for k, v in over.items() if v is not None}
    # 0 means "no limit" (None) for the arrow knobs; only set them when given
    for flag, key in (
        (args.edge_fanin, "edge_fanin"),
        (args.edge_data_max_hops, "edge_data_max_hops"),
    ):
        if flag is not None:
            over[key] = None if flag == 0 else flag
    if args.preset:
        return Controls.preset(args.preset, **over)
    return Controls(**over)


def _add_run(p: argparse.ArgumentParser) -> None:
    p.add_argument("--mode", choices=["heuristic", "teacher", "dry-run"], default="heuristic")
    p.add_argument(
        "--store-only",
        action="store_true",
        help="teacher mode without API: use Run Store results only",
    )
    p.add_argument(
        "--no-spec", action="store_true", help="do not give manifest specs to the teacher"
    )
    p.add_argument(
        "--target",
        nargs="+",
        choices=["block", "fsm", "timing"],
        default=["block"],
        help=(
            "which diagrams to prepare data for: block (anchors/region), fsm (state machines), "
            "timing (placeholder)"
        ),
    )
    _add_controls(p)
    p.add_argument("--k", type=int, default=1)
    p.add_argument("--passes", type=int, default=1, help="multi-pass self-audit rounds (API mode)")
    p.add_argument(
        "--use-round", choices=["final", "first"], default="final", help="which round to use (A/B)"
    )
    p.add_argument("--no-refine", action="store_true")
    p.add_argument(
        "--force-api", action="store_true", help="also send trivial modules to the teacher"
    )
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument(
        "--effort",
        default="high",
        choices=["low", "medium", "high", "xhigh", "max", "session"],
        help="session = annotations written by a Claude session, no API",
    )
    p.add_argument(
        "--budget", type=float, default=None, help="stop when the Run Store has spent this many USD"
    )
    p.add_argument("--store", default="runs/store")
    p.add_argument("--out", default="runs/out")


def _cfg(args):
    from .llm.teacher import TeacherConfig
    from .pipeline import RunConfig

    return RunConfig(
        mode=args.mode,
        k=args.k,
        refine=not args.no_refine,
        force_api_for_trivial=args.force_api,
        budget_usd=args.budget,
        store_only=getattr(args, "store_only", False),
        passes=getattr(args, "passes", 1),
        use_round=getattr(args, "use_round", "final"),
        teacher=TeacherConfig(model=args.model, effort=args.effort),
        controls=_controls(args),
        targets=frozenset(getattr(args, "target", None) or ["block"]),
    )


def _annotate(d: dict, args, store=None):
    from .pipeline import annotate_design
    from .store import RunStore

    if store is None and args.mode == "teacher":
        store = RunStore(args.store)
    spec = None
    if d.get("spec") and not getattr(args, "no_spec", False):
        spec = Path(d["spec"]).read_text(encoding="utf-8", errors="replace")
    return annotate_design(
        d["files"],
        top=d["top"],
        filelist=d["filelist"],
        include_dirs=d["include_dirs"],
        defines=d["defines"],
        cfg=_cfg(args),
        store=store,
        out_dir=args.out,
        name=d["name"],
        spec=spec,
    )


# ------------------------------------------------------------------ commands
def cmd_entities(args):
    from .frontend import build_entity_tables, build_graph, elaborate
    from .llm.prompt import render_entity_table

    for d in _designs(args):
        des = elaborate(
            d["files"],
            top=d["top"],
            filelist=d["filelist"],
            include_dirs=d["include_dirs"],
            defines=d["defines"],
            name=d["name"],
        )
        G = build_graph(des)
        print(f"# {des.name}: {G.stats()}")
        if des.errors:
            print(f"# elaboration errors: {des.errors[:10]}")
        for t in build_entity_tables(G):
            print(f"\n## {t.module}  ({t.canonical_instance}, L{t.line_start}-{t.line_end})")
            print(render_entity_table(t))


def cmd_run(args):
    for d in _designs(args):
        run = _annotate(d, args)
        print(
            f"== {run.design.name}: graph {run.graph.stats()['nodes']} nodes, "
            f"region {len(run.region.nodes)} "
            f"(reduction {run.region.reduction:.2f}) -> {Path(args.out) / run.design.name}"
        )
        for line in run.log:
            print("   " + line)


def cmd_eval(args):
    from .evaluate import load_gold, report_markdown, score_module, summarize

    gold = load_gold(args.gold)
    scores = []
    for d in _designs(args):
        run = _annotate(d, args)
        tables = run.tables_by_module
        for mod, res in run.results.items():
            if mod in gold and mod not in {s.module for s in scores}:
                scores.append(score_module(gold[mod], res, tables[mod], run.graph, run.region))
    md = report_markdown(
        f"eval mode={args.mode} model={args.model} controls={_controls(args).describe()}", scores
    )
    print(md)
    out = Path(args.out) / f"eval_{args.mode}_{datetime.now():%Y%m%d_%H%M%S}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        md + "\n\n```json\n" + json.dumps(summarize(scores), indent=2) + "\n```\n", encoding="utf-8"
    )
    print(f"\nwritten {out}")


def cmd_augment(args):
    from .augment import rename_variant, transfer_labels
    from .frontend import build_entity_tables, build_graph, elaborate

    out_root = Path(args.out)
    manifest = []
    for d in _designs(args):
        des = elaborate(
            d["files"],
            top=d["top"],
            filelist=d["filelist"],
            include_dirs=d["include_dirs"],
            defines=d["defines"],
            name=d["name"],
        )
        G = build_graph(des)
        tables = build_entity_tables(G)
        standalone = len(tables) == 1
        for t in tables:
            for seed in args.seeds:
                v = rename_variant(
                    t,
                    out_root / d["name"] / t.module,
                    include_ports=standalone and not args.keep_ports,
                    strip_comments=True,
                    seed=seed,
                )
                # other files of the design are reused unchanged
                files = [
                    str(v.path) if Path(f).resolve() == Path(t.file).resolve() else f
                    for f in d["files"]
                ]
                vd = elaborate(
                    files,
                    top=(v.top if d["top"] == t.module and v.top else d["top"]),
                    name=f"{d['name']}__{t.module}__{v.name}",
                )
                vt = {x.module: x for x in build_entity_tables(build_graph(vd))}[
                    v.mapping.get(t.module, t.module)
                ]
                ok = [r.id for r in vt.rows] == [r.id for r in t.rows] and all(
                    v.mapping.get(r0.name, r0.name) == r1.name
                    for r0, r1 in zip(t.rows, vt.rows, strict=False)
                )
                print(
                    f"{d['name']}/{t.module}/{v.name}: ids_preserved={ok} renamed={len(v.mapping)}"
                )
                if not ok:
                    continue
                gp = Path(args.gold) / f"{t.module}.json" if args.gold else None
                if gp and gp.exists():
                    g = transfer_labels(json.loads(gp.read_text(encoding="utf-8")), v.mapping)
                    (v.path.parent / f"{t.module}.gold.json").write_text(
                        json.dumps(g, indent=2), encoding="utf-8"
                    )
                manifest.append(
                    {
                        "name": vd.name,
                        "files": [str(Path(f).resolve()) for f in files],
                        "top": (v.top if d["top"] == t.module and v.top else d["top"]),
                    }
                )
    mp = out_root / "manifest.json"
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"variant manifest: {mp}")


def cmd_batch_plan(args):
    from .store import RunStore

    args.mode = "plan"
    store = RunStore(args.store)
    plan = []
    for d in _designs(args):
        from .pipeline import annotate_design

        cfg = _cfg(argparse.Namespace(**{**vars(args), "mode": "heuristic"}))
        cfg.mode = "plan"
        spec = (
            Path(d["spec"]).read_text(encoding="utf-8", errors="replace")
            if d.get("spec") and not args.no_spec
            else None
        )
        run = annotate_design(
            d["files"],
            top=d["top"],
            filelist=d["filelist"],
            include_dirs=d["include_dirs"],
            defines=d["defines"],
            cfg=cfg,
            store=store,
            name=d["name"],
            spec=spec,
        )
        plan += run.plan
        for line in run.log:
            print(f"  {d['name']}: {line}")
    seen, uniq = set(), []
    for p in plan:
        if p["custom_id"] not in seen:
            seen.add(p["custom_id"])
            uniq.append(p)
    bd = Path("runs/batches")
    bd.mkdir(parents=True, exist_ok=True)
    pf = bd / f"plan_{datetime.now():%Y%m%d_%H%M%S}.json"
    meta = {"model": args.model, "effort": args.effort, "batch_id": None, "units": uniq}
    if args.units_dir:
        from .llm.prompt import SYSTEM_PROMPT
        from .schema import annotation_json_schema

        ud = Path(args.units_dir)
        ud.mkdir(parents=True, exist_ok=True)
        (ud / "_system_prompt.md").write_text(SYSTEM_PROMPT, encoding="utf-8")
        (ud / "_schema.json").write_text(
            json.dumps(annotation_json_schema(), indent=1), encoding="utf-8"
        )
        for u in uniq:
            (ud / f"{u['custom_id']}.prompt.md").write_text(
                u["user"] + (u.get("privileged") or ""), encoding="utf-8"
            )
        meta["units_dir"] = str(ud)
    if args.submit and uniq:
        import anthropic

        from .llm.teacher import submit_batch

        meta["batch_id"] = submit_batch(
            anthropic.Anthropic(), _cfg(args).teacher, [(u["custom_id"], u["user"]) for u in uniq]
        )
    pf.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"{len(uniq)} units planned -> {pf}"
        + (f" (batch {meta['batch_id']})" if meta["batch_id"] else "")
    )


def cmd_batch_collect(args):
    import anthropic

    from .llm.teacher import collect_batch
    from .pipeline import RunConfig, ingest_batch
    from .store import RunStore

    meta = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if not meta.get("batch_id"):
        sys.exit("plan has no batch_id (was it submitted?)")
    client = anthropic.Anthropic()
    while True:
        try:
            res = collect_batch(client, meta["batch_id"], meta["model"])
            break
        except RuntimeError as e:
            if not args.wait:
                sys.exit(str(e))
            print(e, "- waiting 60s")
            time.sleep(60)
    from .llm.teacher import TeacherConfig

    cfg = RunConfig(
        mode="teacher", teacher=TeacherConfig(model=meta["model"], effort=meta["effort"])
    )
    print(ingest_batch(RunStore(args.store), meta["units"], res, cfg))


def cmd_session_ingest(args):
    """Ingest annotations written by a session annotator (no API):
    <units_dir>/<custom_id>.answer.json."""
    from .llm.teacher import TeacherConfig
    from .pipeline import RunConfig, ingest_batch
    from .store import RunStore

    meta = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    ud = Path(args.units_dir or meta["units_dir"])
    res = {}
    for u in meta["units"]:
        cid = u["custom_id"]
        passes = sorted(
            ud.glob(f"{cid}.pass*.json"), key=lambda f: int(f.name.split(".pass")[1].split(".")[0])
        )
        if passes:  # multi-pass session annotation: pass1 = round 0, pass2 = round 1, ...
            res[cid] = [
                {
                    "text": f.read_text(encoding="utf-8"),
                    "stop_reason": "end_turn",
                    "usage": {},
                    "batch": False,
                    "round": int(f.name.split(".pass")[1].split(".")[0]) - 1,
                }
                for f in passes
            ]
            continue
        f = ud / f"{cid}.answer.json"
        if f.exists():
            res[cid] = {
                "text": f.read_text(encoding="utf-8"),
                "stop_reason": "end_turn",
                "usage": {},
                "batch": False,
            }
    cfg = RunConfig(
        mode="teacher", teacher=TeacherConfig(model=meta["model"], effort=meta["effort"])
    )
    st = ingest_batch(RunStore(args.store), meta["units"], res, cfg)
    print(json.dumps(st, indent=1))


def cmd_gold_draft(args):
    """anchors.json (teacher/heuristic output) -> gold/<module>.json drafts for human correction."""
    af = json.loads(Path(args.anchors).read_text(encoding="utf-8"))
    out = Path(args.gold)
    out.mkdir(parents=True, exist_ok=True)
    for mod, res in af["modules"].items():
        if args.module and mod not in args.module:
            continue
        dst = out / f"{mod}.json"
        if dst.exists() and not args.overwrite:
            print(f"skip {dst} (exists)")
            continue
        g = {
            "module": mod,
            "level": res.get("level", "MEDIUM"),
            "status": f"draft from {res['source']} ({Path(args.anchors).as_posix()}); "
            "review: fix roles, add alt_ids, delete extras",
            "anchors": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "role": a["role"],
                    "importance": a["importance"],
                    "alt_ids": [],
                }
                for a in res["anchors"]
            ],
            "groups": [{"name": g["name"], "anchor_ids": g["anchor_ids"]} for g in res["groups"]],
        }
        dst.write_text(json.dumps(g, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {dst}")


def cmd_sweep(args):
    """Frontend robustness + calibration over a manifest (no API)."""
    import statistics as st
    import traceback

    from .frontend import build_entity_tables, build_graph, elaborate
    from .heuristic import heuristic_annotation, is_trivial
    from .schema import ModuleResult, VotedAnchor
    from .trace import compute_region

    rows, fails = [], []
    for d in _designs(args):
        t0 = time.time()
        try:
            des = elaborate(
                d["files"],
                top=d["top"],
                include_dirs=d["include_dirs"],
                defines=d["defines"],
                filelist=d["filelist"],
                name=d["name"],
            )
            G = build_graph(des)
            tables = build_entity_tables(G)
        except Exception as e:
            fails.append((d["name"], f"{type(e).__name__}: {e}"[:300]))
            if args.verbose:
                traceback.print_exc()
            continue
        res = {}
        for t in tables:
            a = heuristic_annotation(t, Level.LOW)
            res[t.module] = ModuleResult(
                module=t.module,
                canonical_instance=t.canonical_instance,
                source="heuristic",
                anchors=[VotedAnchor(**x.model_dump()) for x in a.anchors],
            )
        from dataclasses import replace

        from .controls import apply_view

        red = {}
        base = _controls(args)
        tb = {t.module: t for t in tables}
        for lv in Level:
            c = replace(base, level=lv)
            views = {m: apply_view(r, c, tb.get(m)) for m, r in res.items()}
            r = compute_region(
                G,
                tb,
                views,
                level=lv,
                threshold=c.threshold,
                depth=c.depth,
                reg_hops=c.reg_hops,
                steiner=c.steiner,
                include_top_ports=c.include_ports,
                budget=c.max_region_nodes,
            )
            red[lv.value] = r.reduction
        rows.append(
            {
                "name": d["name"],
                "errors": len(des.errors),
                "nodes": G.g.number_of_nodes(),
                "edges": G.g.number_of_edges(),
                "modules": len(tables),
                "trivial": sum(is_trivial(t) for t in tables),
                "fsm": sum(r.fsm_candidate for t in tables for r in t.rows),
                "entities": sum(len(t.rows) for t in tables),
                "unsupported": len(G.unsupported),
                "sec": round(time.time() - t0, 3),
                **{f"red_{k}": round(v, 3) for k, v in red.items()},
            }
        )
    out = Path(args.out) / f"sweep_{Path(args.manifest).stem if args.manifest else 'files'}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows, "fails": fails}, indent=1), encoding="utf-8")
    n = len(rows) + len(fails)
    print(f"designs: {n}  elaborated: {len(rows)}  failed: {len(fails)}")
    if rows:
        print(
            f"with slang errors: {sum(r['errors'] > 0 for r in rows)}   "
            f"unsupported constructs: {sum(r['unsupported'] > 0 for r in rows)}"
        )
        print(
            f"nodes median {st.median(r['nodes'] for r in rows)} "
            f"max {max(r['nodes'] for r in rows)}; "
            f"trivial modules {sum(r['trivial'] for r in rows)}/{sum(r['modules'] for r in rows)}; "
            f"designs with FSM candidates {sum(r['fsm'] > 0 for r in rows)}"
        )
        big = [r for r in rows if r["nodes"] >= 20]
        for lv in Level:
            k = f"red_{lv.value}"
            if big:
                print(
                    f"reduction {lv.value:6s} (designs >=20 nodes, n={len(big)}): "
                    f"median {st.median(r[k] for r in big):.2f}"
                )
    for name, e in fails:
        print(f"FAIL {name}: {e}")
    print(f"written {out}")


def cmd_calibrate(args):
    from .calibrate import calibrate, markdown
    from .store import RunStore

    designs = []
    for m in args.manifests:
        args.manifest = m
        designs += _designs(args)
    rep = calibrate(
        designs,
        store=RunStore(args.store),
        model=args.model,
        effort=args.effort,
        base=_controls(args),
        gold_dir=args.gold,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown(rep), encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps(rep["summary"], indent=1))
    print(f"written {out}")


def cmd_diagram(args):
    from .diagram import render, to_dot

    for d in _designs(args):
        run = _annotate(d, args)
        c = run.controls
        tag = args.preset or c.level.value
        dot = to_dot(
            run.graph,
            run.tables_by_module,
            run.results,
            run.region,
            title=f"{run.design.name} [{tag}] "
            f"anchors={sum(len(r.anchors) for r in run.results.values())} "
            f"arrows={len(run.region.anchor_edges)}",
        )
        if "block" in run.targets:
            svg = render(dot, Path(args.out) / run.design.name / f"diagram_{tag}.svg")
            print(svg or "graphviz `dot` not found; wrote .dot only")
        for f in run.fsms:
            svg = render(
                f.dot(), Path(args.out) / run.design.name / "fsm" / f"{f.module}.{f.state}.svg"
            )
            print(svg or f"wrote {f.module}.{f.state}.dot")


def cmd_export(args):
    from .distill.export import export_sft
    from .store import RunStore

    print(export_sft(RunStore(args.store), args.out, min_confidence=args.min_conf))
    if args.split_dir:
        from .distill.export import assemble_sft

        print(assemble_sft(args.out, args.augment or [], args.split_dir))


def cmd_cost(args):
    from .store import RunStore

    s = RunStore(args.store)
    rows = s.db.execute(
        "SELECT module, COUNT(*), SUM(usd), SUM(ok) FROM runs "
        "GROUP BY module ORDER BY SUM(usd) DESC"
    ).fetchall()
    for m, n, usd, ok in rows:
        print(f"{m:30s} runs={n:3d} ok={ok:3d} ${usd or 0:.4f}")
    print(f"TOTAL ${s.spent_usd():.4f}")


def cmd_yosys(args):
    from .frontend import build_entity_tables, build_graph, elaborate
    from .frontend.yosys_check import yosys_fsm_candidates

    for d in _designs(args):
        des = elaborate(d["files"], top=d["top"], name=d["name"])
        ours = {
            (t.module, r.name)
            for t in build_entity_tables(build_graph(des))
            for r in t.rows
            if r.fsm_candidate
        }
        try:
            theirs = yosys_fsm_candidates(d["files"], d["top"])
        except Exception as e:  # yosys frontend may reject valid SV
            print(f"{d['name']}: yosys unavailable/failed: {e}")
            continue
        print(
            f"{d['name']}: both={sorted(ours & theirs)} only_l1={sorted(ours - theirs)} "
            f"only_yosys={sorted(theirs - ours)}"
        )


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m rtl2d_l1.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("entities")
    _add_src(p)
    p.set_defaults(fn=cmd_entities)
    p = sub.add_parser("run")
    _add_src(p)
    _add_run(p)
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("eval")
    _add_src(p)
    _add_run(p)
    p.add_argument("--gold", default="gold")
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("augment")
    _add_src(p)
    p.add_argument("--gold", default="gold")
    p.add_argument("--seeds", type=int, nargs="+", default=[0])
    p.add_argument("--keep-ports", action="store_true")
    p.add_argument("--out", default="runs/augment")
    p.set_defaults(fn=cmd_augment)

    b = sub.add_parser("batch").add_subparsers(dest="bcmd", required=True)
    p = b.add_parser("plan")
    _add_src(p)
    _add_run(p)
    p.add_argument("--submit", action="store_true")
    p.add_argument(
        "--units-dir", default=None, help="also write one prompt file per unit (session annotation)"
    )
    p.set_defaults(fn=cmd_batch_plan)
    p = b.add_parser("ingest-session")
    p.add_argument("plan")
    p.add_argument("--units-dir", default=None)
    p.add_argument("--store", default="runs/store")
    p.set_defaults(fn=cmd_session_ingest)
    p = b.add_parser("collect")
    p.add_argument("plan")
    p.add_argument("--wait", action="store_true")
    p.add_argument("--store", default="runs/store")
    p.set_defaults(fn=cmd_batch_collect)

    p = sub.add_parser("export-sft")
    p.add_argument("--augment", nargs="*", default=None, help="rename-augmented sample files")
    p.add_argument("--split-dir", default=None, help="write train/eval split by original module")
    p.add_argument("--out", default="runs/sft.jsonl")
    p.add_argument("--min-conf", type=float, default=0.67)
    p.add_argument("--store", default="runs/store")
    p.set_defaults(fn=cmd_export)
    p = sub.add_parser("gold-draft")
    p.add_argument("anchors")
    p.add_argument("--gold", default="gold")
    p.add_argument("--module", nargs="*")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(fn=cmd_gold_draft)
    p = sub.add_parser("sweep")
    _add_src(p)
    _add_controls(p)
    p.add_argument("--out", default="runs/out")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(fn=cmd_sweep)
    p = sub.add_parser("diagram")
    _add_src(p)
    _add_run(p)
    p.set_defaults(fn=cmd_diagram)
    p = sub.add_parser("calibrate")
    p.add_argument("manifests", nargs="+")
    _add_controls(p)
    p.add_argument("--model", default="claude-session")
    p.add_argument("--effort", default="session")
    p.add_argument("--store", default="runs/store")
    p.add_argument("--gold", default="gold")
    p.add_argument("--out", default="runs/out/calibration.md")
    p.set_defaults(fn=cmd_calibrate)
    p = sub.add_parser("cost")
    p.add_argument("--store", default="runs/store")
    p.set_defaults(fn=cmd_cost)
    p = sub.add_parser("yosys-check")
    _add_src(p)
    p.set_defaults(fn=cmd_yosys)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
