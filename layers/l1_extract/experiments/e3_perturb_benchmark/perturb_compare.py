"""Compare what Stage 1 extracts from an original design vs its equivalent messy rewrites.

  python experiments/e3_perturb_benchmark/perturb_compare.py manifests
      # write data/manifest_{orig,S1,S2}.json
  python experiments/e3_perturb_benchmark/perturb_compare.py fsm
      # deterministic FSM comparison
  python experiments/e3_perturb_benchmark/perturb_compare.py anchors [--round first|final]
      # teacher anchors (from the Run Store)

Teacher comparison is by NAME through each rewrite's mapping.json (internal names all changed).
"""

import json
import os
import sys
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]  # layers/l1_extract
P = Path(__file__).resolve().parent / "data"
designs = json.loads((P / "designs.json").read_text(encoding="utf-8"))
STYLES = ("S1", "S2")
# --importance tier|score|structure: how views pick levels
# ("tier" results keep the old file names)
IMP = sys.argv[sys.argv.index("--importance") + 1] if "--importance" in sys.argv else "tier"
# --model: which annotator's Run Store records to compare (default: the Opus-level session teacher)
MODEL = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "claude-session"
SUFFIX = ("" if IMP == "tier" else f"_{IMP}") + ("" if MODEL == "claude-session" else f"_{MODEL}")


def rewrite_files(name, style):
    d = P / name / style
    return (
        sorted(str(f.resolve()) for f in d.glob("*") if f.suffix in (".v", ".sv"))
        if d.exists()
        else []
    )


def mapping(name, style):
    f = P / name / style / "mapping.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def cmd_manifests():
    orig, per = [], {s: [] for s in STYLES}
    for x in designs:
        orig.append(
            {
                "name": f"orig_{x['name']}",
                "files": [Path(os.path.relpath(ROOT / f, P)).as_posix() for f in x["files"]],
                "top": x["top"],
            }
        )
        for s in STYLES:
            fs = rewrite_files(x["name"], s)
            if fs and mapping(x["name"], s):
                per[s].append(
                    {
                        "name": f"{s}_{x['name']}",
                        "files": [Path(os.path.relpath(f, P)).as_posix() for f in fs],
                        "top": x["top"],
                    }
                )
    (P / "manifest_orig.json").write_text(json.dumps(orig, indent=1), encoding="utf-8")
    for s in STYLES:
        (P / f"manifest_{s}.json").write_text(json.dumps(per[s], indent=1), encoding="utf-8")
    print({"orig": len(orig), **{s: len(v) for s, v in per.items()}})


# ------------------------------------------------------------------------- FSM
def fsms_of(files, top):
    from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate
    from rtl2d_l1.frontend.fsm import extract_fsms

    d = elaborate(files, top=top)
    G = build_graph(d)
    return extract_fsms(d, G, build_entity_tables(G))


def fsm_graph(f):
    names = [s["name"] for s in f.states]
    g = nx.DiGraph()
    for n in names:
        g.add_node(n, reset=(n == f.reset_state))
    for t in f.transitions:
        for s in names if t.src == "*" else [t.src]:
            if s != t.dst:
                g.add_edge(s, t.dst)
    return g


def cmd_fsm():
    """Both extractors on original vs rewrites.
    syntactic: case/==-pattern extractor (fsm.py)       semantic: execution-based (fsm_semantic.py)
    A rewrite 'preserves' an FSM when the rewrite yields a state graph isomorphic to the original's
    (reset state marked), found WITHOUT using the rewrite's name mapping."""
    from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate
    from rtl2d_l1.frontend.fsm_semantic import detect, state_graph

    def run(files, top):
        d = elaborate(files, top=top)
        G = build_graph(d)
        T = build_entity_tables(G)
        from rtl2d_l1.frontend.fsm import extract_fsms

        syn = extract_fsms(d, G, T)
        syn_keys = {
            k
            for t in T
            for r in t.rows
            if r.fsm_candidate
            for k in ([*r.members] if r.members else [f"{t.canonical_instance}.{r.name}"])
        }
        sem = detect(d, G, syn_keys)
        return syn, sem

    rows = []
    for x in designs:
        osyn, osem = run([str(ROOT / f) for f in x["files"]], x["top"])
        refs = [r for r in osem if not r.error]
        if not refs:
            continue
        for st in STYLES:
            fs = rewrite_files(x["name"], st)
            if not fs or mapping(x["name"], st) is None:
                continue
            rsyn, rsem = run(fs, x["top"])
            for o in refs:
                go = state_graph(o)
                # syntactic extractor on the rewrite: any FSM with isomorphic transition graph?
                syn_ok = False
                for f in rsyn:
                    names = [q["name"] for q in f.states]
                    g = nx.DiGraph()
                    for n in names:
                        g.add_node(n, reset=(n == f.reset_state))
                    for t in f.transitions:
                        for a in names if t.src == "*" else [t.src]:
                            if a != t.dst:
                                g.add_edge(a, t.dst)
                    if nx.is_isomorphic(go, g, node_match=lambda a, b: a["reset"] == b["reset"]):
                        syn_ok = True
                sem_ok, match = False, "-"
                for r in rsem:
                    if r.error:
                        continue
                    if nx.is_isomorphic(
                        go, state_graph(r), node_match=lambda a, b: a["reset"] == b["reset"]
                    ):
                        sem_ok, match = True, r.state
                        break
                if not sem_ok and rsem:
                    best = min(
                        (r for r in rsem if not r.error),
                        key=lambda r: abs(len(r.states) - len(o.states)),
                        default=None,
                    )
                    if best:
                        match = (
                            f"closest {best.state} {len(best.states)}st/"
                            f"{state_graph(best).number_of_edges()}e"
                        )
                rows.append(
                    {
                        "design": x["name"],
                        "style": st,
                        "orig": o.state.split(".")[-1],
                        "states": len(o.states),
                        "edges": go.number_of_edges(),
                        "syntactic": syn_ok,
                        "semantic": sem_ok,
                        "match": match,
                    }
                )
    print(f"{'design':18s} {'st':3s} {'fsm':12s} {'S/E':7s} syntactic semantic  rewrite register")
    for r in rows:
        print(
            f"{r['design']:18s} {r['style']:3s} {r['orig']:12s} {r['states']:>2}/{r['edges']:<4} "
            f"{'PASS' if r['syntactic'] else 'fail':9s} "
            f"{'PASS' if r['semantic'] else 'fail':8s} {r['match']}"
        )
    n = len(rows)
    print(
        "\nFSM preserved (isomorphic, no name mapping used): "
        f"syntactic {sum(r['syntactic'] for r in rows)}/{n}, "
        f"semantic {sum(r['semantic'] for r in rows)}/{n}"
    )
    (P / "fsm_compare.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


# --------------------------------------------------------------------- anchors
def anchors_of(manifest_entry, use_round):
    from rtl2d_l1.controls import Controls, apply_view
    from rtl2d_l1.llm.teacher import TeacherConfig
    from rtl2d_l1.pipeline import RunConfig, annotate_design
    from rtl2d_l1.store import RunStore
    from rtl2d_l1.taxonomy import Level

    cfg = RunConfig(
        mode="teacher",
        store_only=True,
        refine=False,
        use_round=use_round,
        teacher=TeacherConfig(model=MODEL, effort="session"),
    )
    run = annotate_design(
        manifest_entry["files"],
        top=manifest_entry["top"],
        cfg=cfg,
        store=RunStore(ROOT / "runs/store"),
        name=manifest_entry["name"],
    )
    out = {lv: {} for lv in ("HIGH", "MEDIUM", "LOW")}
    sources = {m: r.source for m, r in run.results_full.items()}
    for m, r in run.results_full.items():
        for lv in out:
            for a in apply_view(
                r, Controls(level=Level(lv), importance=IMP), run.tables_by_module.get(m)
            ).anchors:
                out[lv][a.name.split(".")[-1]] = a.role.value
    return out, sources


def anchor_nodes(manifest_entry, use_round):
    """Per level: {node key: role} for teacher anchors of every module instance (flattened)."""
    from rtl2d_l1.controls import Controls, apply_view
    from rtl2d_l1.llm.teacher import TeacherConfig
    from rtl2d_l1.pipeline import RunConfig, annotate_design
    from rtl2d_l1.store import RunStore
    from rtl2d_l1.taxonomy import Level
    from rtl2d_l1.trace import entity_nodes

    cfg = RunConfig(
        mode="teacher",
        store_only=True,
        refine=False,
        use_round=use_round,
        teacher=TeacherConfig(model=MODEL, effort="session"),
    )
    run = annotate_design(
        manifest_entry["files"],
        top=manifest_entry["top"],
        cfg=cfg,
        store=RunStore(ROOT / "runs/store"),
        name=manifest_entry["name"],
    )
    out = {lv: {} for lv in ("HIGH", "MEDIUM", "LOW")}
    # modules still waiting for a teacher result (trivial modules are heuristic by design,
    # not missing)
    missing = [
        m
        for m, r in run.results_full.items()
        if r.source != "teacher" and not any("trivial" in w for w in r.warnings)
    ]
    for m, r in run.results_full.items():
        t = run.tables_by_module[m]
        for lv in out:
            for a in apply_view(r, Controls(level=Level(lv), importance=IMP), t).anchors:
                for k in entity_nodes(run.graph, t, a.id):
                    out[lv][k] = a.role.value
    return out, run.graph, missing


def alias_classes(G):
    """Union-find over physical-signal aliases: instance port connections and pure copies
    (x = y)."""
    parent = {k: k for k in G.nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for s, t, d in G.g.edges(data=True):
        et = d["type"].value
        pure_copy = et == "DATA" and len(G.preds(t)) == 1 and G.nodes[s].width == G.nodes[t].width
        if et == "PORT" or pure_copy:
            parent[find(s)] = find(t)
    return find


def cmd_anchors_physical(use_round):
    """Concept match by PHYSICAL signal: an original anchor is recovered when some rewrite anchor
    is the same signal (through renames via mapping.json, instance ports and pure copies)."""
    rows = []
    for x in designs:
        o, Go, miss_o = anchor_nodes(
            {
                "name": f"orig_{x['name']}",
                "files": [str((ROOT / f).resolve()) for f in x["files"]],
                "top": x["top"],
            },
            use_round,
        )
        if miss_o:
            continue
        for s in STYLES:
            fs = rewrite_files(x["name"], s)
            m = mapping(x["name"], s)
            if not fs or m is None:
                continue
            r, Gr, miss_r = anchor_nodes(
                {
                    "name": f"{s}_{x['name']}",
                    "files": fs,
                    "top": x["top"],
                },
                use_round,
            )
            find = alias_classes(Gr)
            ren = {k: v for k, v in (m.get("signals") or {}).items()}
            for k, v in (m.get("moved_to_submodule") or {}).items():
                ren[k] = v
            by_name = {}
            for k, n in Gr.nodes.items():
                by_name.setdefault(n.rel, []).append(k)
                by_name.setdefault(n.name, []).append(k)
            row = {"design": x["name"], "style": s, "unannotated_modules": miss_r}
            for lv in ("HIGH", "MEDIUM", "LOW"):
                r_classes = {find(k): role for k, role in r[lv].items()}
                hit = tot = role_ok = 0
                covered_classes = set()
                for ok_, role in o[lv].items():
                    nm = Go.nodes[ok_].rel
                    target = ren.get(nm, nm)
                    if target is None:
                        continue  # eliminated by the rewrite (e.g. a next-state twin)
                    keys = by_name.get(str(target), []) or by_name.get(
                        str(target).split(".")[-1], []
                    )
                    if not keys:
                        continue
                    tot += 1
                    cls = {find(k) for k in keys}
                    if cls & set(r_classes):
                        hit += 1
                        covered_classes |= cls & set(r_classes)
                        role_ok += any(r_classes[c] == role for c in cls & set(r_classes))
                row[f"recall_{lv}"] = round(hit / tot, 3) if tot else None
                row[f"precision_{lv}"] = (
                    round(len(covered_classes) / len(r_classes), 3) if r_classes else None
                )
                if lv == "MEDIUM":
                    row["role_agree_MEDIUM"] = round(role_ok / hit, 3) if hit else None
            rows.append(row)
    for r in rows:
        print(
            f"{r['design']:18s} {r['style']} recall H/M/L "
            f"{r['recall_HIGH']}/{r['recall_MEDIUM']}/{r['recall_LOW']} "
            f"prec M {r['precision_MEDIUM']} role M {r['role_agree_MEDIUM']}"
            + (f"  (unannotated: {r['unannotated_modules']})" if r["unannotated_modules"] else "")
        )

    def mean(k, rs):
        v = [x[k] for x in rs if x[k] is not None]
        return round(sum(v) / len(v), 3) if v else None

    summ = {}
    for s in STYLES:
        rs = [r for r in rows if r["style"] == s and not r["unannotated_modules"]]
        summ[s] = {
            k: mean(k, rs)
            for k in (
                "recall_HIGH",
                "recall_MEDIUM",
                "recall_LOW",
                "precision_MEDIUM",
                "role_agree_MEDIUM",
            )
        }
        summ[s]["n"] = len(rs)
    print(json.dumps(summ, indent=1))
    (P / f"anchor_compare_physical_{use_round}{SUFFIX}.json").write_text(
        json.dumps({"summary": summ, "rows": rows}, indent=1), encoding="utf-8"
    )


def cmd_anchors(use_round):
    rows = []
    for x in designs:
        o, osrc = anchors_of(
            {
                "name": f"orig_{x['name']}",
                "files": [str((ROOT / f).resolve()) for f in x["files"]],
                "top": x["top"],
            },
            use_round,
        )
        if "teacher" not in osrc.values():
            continue
        for s in STYLES:
            fs = rewrite_files(x["name"], s)
            m = mapping(x["name"], s)
            if not fs or m is None:
                continue
            r, rsrc = anchors_of(
                {
                    "name": f"{s}_{x['name']}",
                    "files": fs,
                    "top": x["top"],
                },
                use_round,
            )
            if "teacher" not in rsrc.values():
                continue
            ren = {k: v for k, v in (m.get("signals") or {}).items()}
            for k, v in (m.get("moved_to_submodule") or {}).items():
                ren[k] = str(v).split(".")[-1]
            row = {"design": x["name"], "style": s}
            for lv in ("HIGH", "MEDIUM", "LOW"):
                oa, ra = o[lv], r[lv]
                mapped = {ren.get(n, n): role for n, role in oa.items() if ren.get(n, n)}
                hit = [n for n in mapped if n in ra]
                row[f"recall_{lv}"] = round(len(hit) / len(mapped), 3) if mapped else None
                inv = set(mapped)
                row[f"precision_{lv}"] = (
                    round(sum(1 for n in ra if n in inv) / len(ra), 3) if ra else None
                )
                if lv == "MEDIUM":
                    row["role_agree_MEDIUM"] = (
                        round(sum(mapped[n] == ra[n] for n in hit) / len(hit), 3) if hit else None
                    )
                    row["missed_MEDIUM"] = [n for n in mapped if n not in ra]
                    row["extra_MEDIUM"] = [n for n in ra if n not in inv]
            rows.append(row)
    for r in rows:
        print(
            f"{r['design']:18s} {r['style']} recall H/M/L "
            f"{r['recall_HIGH']}/{r['recall_MEDIUM']}/{r['recall_LOW']} "
            f"prec M {r['precision_MEDIUM']} role M {r['role_agree_MEDIUM']}  "
            f"missed {r['missed_MEDIUM']} extra {r['extra_MEDIUM']}"
        )

    def mean(k, rs):
        v = [x[k] for x in rs if x[k] is not None]
        return round(sum(v) / len(v), 3) if v else None

    summ = {}
    for s in STYLES + ("ALL",):
        rs = [r for r in rows if s == "ALL" or r["style"] == s]
        summ[s] = {
            k: mean(k, rs)
            for k in (
                "recall_HIGH",
                "recall_MEDIUM",
                "recall_LOW",
                "precision_MEDIUM",
                "role_agree_MEDIUM",
            )
        }
        summ[s]["n"] = len(rs)
    print(json.dumps(summ, indent=1))
    (P / f"anchor_compare_{use_round}{SUFFIX}.json").write_text(
        json.dumps({"summary": summ, "rows": rows}, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    c = sys.argv[1]
    if c == "manifests":
        cmd_manifests()
    elif c == "fsm":
        cmd_fsm()
    elif c == "anchors":
        cmd_anchors(sys.argv[sys.argv.index("--round") + 1] if "--round" in sys.argv else "final")
    elif c == "physical":
        cmd_anchors_physical(
            sys.argv[sys.argv.index("--round") + 1] if "--round" in sys.argv else "final"
        )
