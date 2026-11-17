"""Gallery 用的架構圖驅動程式：沿用專案 x2（teacher-v1 標註 + x1 bridge + adapter + e3 引擎）
與 x1（system / paper 兩種內建畫法）的既有函式，不修改任何 src/。
    python gal_block.py A <name> [root]    bridge + adapter + e3 engines
    python gal_block.py B <tag>            x1 system / paper renderers
"""
import json, signal, sys, time, traceback
from pathlib import Path

import os
ROOT = Path(os.environ.get("GAL_ROOT", str(Path.home() / "rtl2d-demo/repo")))
X1 = ROOT / "pipeline/experiments/x1_l1_to_l3"
X2 = ROOT / "pipeline/experiments/x2_l1_to_paper"
E3 = ROOT / "layers/l3_draw/experiments/e3_paper_engines"
OUT = ROOT / os.environ.get("GAL_OUT", "runs/gallery_block")
mode = sys.argv[1]


class Timeout(Exception):
    pass


def _alarm(*_):
    raise Timeout()


signal.signal(signal.SIGALRM, _alarm)


def guarded(fn, seconds):
    signal.alarm(seconds)
    t0 = time.perf_counter()
    try:
        return "ok", fn(), round(time.perf_counter() - t0, 2)
    except Timeout:
        return "timeout", None, seconds
    except Exception as e:  # noqa: BLE001
        tb = traceback.extract_tb(e.__traceback__)[-1]
        return "error", f"{type(e).__name__}: {str(e)[:160]} @ {Path(tb.filename).name}:{tb.lineno}", round(time.perf_counter() - t0, 2)
    finally:
        signal.alarm(0)


if mode == "A":
    name = sys.argv[2]
    root = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != "-" else None
    tag = name if not root else f"{name}@{root}"
    for p in (str(X2), str(X1), str(E3)):   # 與 x2/run.py 相同的順序
        sys.path.insert(0, p)
    import adapter
    import p3lib
    import bridge
    import teacher_v1
    ents = {e["name"]: e for e in json.loads(Path(os.environ.get("GAL_MANIFEST", str(ROOT / "runs/gallery_manifest.json"))).read_text())}
    e = ents[name]
    entry = {"name": name, "top": e["top"], "files": [str(ROOT / f) for f in e["files"]]}
    out = OUT / tag
    out.mkdir(parents=True, exist_ok=True)
    report = []
    bridge.annotate_design = teacher_v1.patched_annotate(name, report)
    bridge.RunStore = lambda *_a, **_k: None
    res = {"tag": tag, "design": name, "root": root, "engines": {}}
    st, val, dt = guarded(lambda: bridge.build(entry, root=root), 600)
    res["bridge"] = {"status": st, "seconds": dt}
    if st != "ok":
        res["bridge"]["error"] = val
        (out / "block.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
        print(tag, "bridge", st, val)
        sys.exit(0)
    d, h, m = val
    for k, v in (("diagram", d), ("hints", h), ("meta", m)):
        (out / f"x1.{k}.json").write_text(json.dumps(v, indent=1, ensure_ascii=False))
    bad = p3lib.spec.validate(p3lib.spec.Diagram.model_validate(d))
    nd, side, notes = adapter.adapt(d, m)
    errs, relaxed = adapter.check(nd)
    (out / "e3.diagram.json").write_text(json.dumps(nd, indent=1, ensure_ascii=False))
    (out / "e3.side.json").write_text(json.dumps(side, indent=1, ensure_ascii=False))
    res["bridge"].update(blocks=len(d["blocks"]), nets=len(d["nets"]), view=m.get("view"), issues=len(bad),
                         units=len(nd["blocks"]), unit_nets=len(nd["nets"]), adapter_errors=errs[:3],
                         relaxed=len(relaxed), notes=(notes + report)[:8],
                         groups=[g["name"] for g in m.get("teacher_groups", [])],
                         interfaces=[i["name"] for i in m.get("interfaces", [])])
    import avoidroute, check, grammar, layout, measure3, paper
    dm = p3lib.spec.Diagram.model_validate(nd)
    g = grammar.build(tag, dm, side)
    lost = grammar.check(g, dm)
    res["grammar"] = {"lost": len(lost), "units": sum(1 for n in g.nodes.values() if n.kind in ("leaf", "bar")),
                      "containers": len(g.containers()), "edges": len(g.edges)}
    for eng in sys.argv[4].split(",") if len(sys.argv) > 4 else ["busbar", "dot", "hola", "grid"]:
        def run(eng=eng):
            pl = layout.ENGINES[eng](g, seconds=20.0)
            rt = avoidroute.route(g, pl)
            svg = paper.render(g, pl, rt, f"{tag}   {eng}")
            (out / f"e3.{eng}.svg").write_text(svg)
            mm = measure3.measure(g, pl, rt)
            issues = check.roundtrip(g, dm, svg)
            return {**mm, "score": list(measure3.score(mm)), "roundtrip": len(issues), "notes": " | ".join(pl.notes)[:200]}
        st, val, dt = guarded(run, 240)
        res["engines"][eng] = {"status": st, "seconds": dt, **(val if isinstance(val, dict) else {"error": val})}
    (out / "block.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str))
    b = res["bridge"]
    print(tag, "bridge ok", f"blocks={b['blocks']} nets={b['nets']} view={b['view']} units={b['units']}",
          {k: (v["status"], v.get("crossings", v.get("cross")), v.get("roundtrip")) for k, v in res["engines"].items()}, "notes:", b["notes"][:2])
else:
    tag = sys.argv[2]
    sys.path.insert(0, str(X1))
    out = OUT / tag
    ld = lambda k: json.loads((out / f"x1.{k}.json").read_text())
    res = {}
    import system
    st, val, dt = guarded(lambda: system.render(ld("diagram"), ld("hints"), ld("meta"), title=tag), 240)
    if st == "ok":
        (out / "x1.system.svg").write_text(val[0]); res["system"] = {"status": st, "seconds": dt, **val[1]}
    else:
        res["system"] = {"status": st, "error": val}
    import paper
    st, val, dt = guarded(lambda: paper.render(ld("diagram"), ld("hints"), ld("meta"), title=tag), 240)
    if st == "ok":
        (out / "x1.paper.svg").write_text(val[0]); res["paper"] = {"status": st, "seconds": dt, **val[1]}
    else:
        res["paper"] = {"status": st, "error": val}
    (out / "x1.json").write_text(json.dumps(res, indent=1, default=str))
    print(tag, {k: (v["status"], v.get("cross"), v.get("error", "")[:80] if isinstance(v.get("error"), str) else "") for k, v in res.items()})
