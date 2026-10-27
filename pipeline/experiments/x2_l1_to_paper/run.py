"""x2: RTL -> L1 (front end + teacher-v1 labels) -> x1 bridge (L2 stand-in) -> adapter ->
L3 e3 paper-figure engines. Nothing in any layer's src/ is changed or imported across
layers; this experiment loads L1's package, x1's bridge and e3's modules, as x1 did.

    uv run --package rtl2d-l1 --with nodejs-wheel --with ortools python \\
        pipeline/experiments/x2_l1_to_paper/run.py [--only REGEX] [--engines a,b] [--jobs 6]
Output: runs/x2_l1_to_paper/{inputs/,svg/,png/,results.json,gallery.html,blind.html}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
L1 = ROOT / "layers" / "l1_extract"
X1 = ROOT / "pipeline" / "experiments" / "x1_l1_to_l3"
E3 = ROOT / "layers" / "l3_draw" / "experiments" / "e3_paper_engines"
OUT = ROOT / "runs" / "x2_l1_to_paper"
for p in (str(HERE), str(X1), str(E3)):
    if p not in sys.path:
        sys.path.insert(0, p)

import adapter  # noqa: E402
import p3lib  # noqa: E402  (e3 paths; puts e0/e1/e2 on sys.path)

DESIGNS = ["picorv32_picosoc", "dark_darksocv", "verilog-ethernet_udp_complete",
           "verilog-ethernet_ip_complete", "verilog-ethernet_eth_mac_1g_rgmii_fifo",
           "verilog-axi_axi_crossbar", "verilog-axis_axis_ram_switch", "serv_serv_top",
           "wb2axip_axim2wbsp"]
ENGINES = ["elk", "dot", "hola", "busbar", "cola", "grid", "d2_tala", "d2_dagre"]


def eval_entry(name: str) -> dict:
    ev = {e["name"]: e for e in json.loads((X1 / "eval_set.json").read_text())}
    e = dict(ev[name])
    e["files"] = [str(L1 / f.replace("data/corpus/", "data/rtl/")) for f in e["files"]]
    return e


def bridge_one(name: str) -> dict:
    """L1 + bridge + adapter for one design; writes runs/x2_l1_to_paper/inputs/<name>.*"""
    import bridge
    import teacher_v1

    report: list[str] = []
    bridge.annotate_design = teacher_v1.patched_annotate(name, report)
    bridge.RunStore = lambda *_a, **_k: None  # teacher-v1 replaces the store
    t0 = time.perf_counter()
    d, h, m = bridge.build(eval_entry(name))
    bad = p3lib.spec.validate(p3lib.spec.Diagram.model_validate(d))
    nd, side, notes = adapter.adapt(d, m)
    errs, relaxed = adapter.check(nd)
    inp = OUT / "inputs"
    inp.mkdir(parents=True, exist_ok=True)
    for k, v in (("bridge", d), ("meta", m), ("diagram", nd), ("side", side)):
        (inp / f"{name}.{k}.json").write_text(json.dumps(v, indent=1, ensure_ascii=False))
    return {"design": name, "seconds": round(time.perf_counter() - t0, 1),
            "bridge_blocks": len(d["blocks"]), "bridge_nets": len(d["nets"]),
            "bridge_issues": bad[:3], "units": len(nd["blocks"]), "nets": len(nd["nets"]),
            "adapter_errors": errs[:3], "relaxed": len(relaxed), "notes": notes + report,
            "groups": [g["name"] for g in m.get("teacher_groups", [])],
            "interfaces": [i["name"] for i in m.get("interfaces", [])]}


def draw_one(job: dict) -> dict:
    import avoidroute
    import check
    import d2out
    import grammar
    import layout
    import measure3
    import paper
    from e3run import png_to

    name, eng = job["input"], job["engine"]
    row = {"input": name, "engine": eng}
    t0 = time.perf_counter()
    out = OUT / "svg" / name / f"{eng}.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        inp = OUT / "inputs"
        d = p3lib.spec.Diagram.model_validate_json((inp / f"{name}.diagram.json").read_text())
        side = json.loads((inp / f"{name}.side.json").read_text())
        g = grammar.build(name, d, side)
        lost = grammar.check(g, d)
        if lost:
            raise RuntimeError(f"grammar lost {len(lost)} sinks: {lost[0]}")
        row.update(units=sum(1 for n in g.nodes.values() if n.kind in ("leaf", "bar")),
                   containers=len(g.containers()), edges=len(g.edges))
        if eng.startswith("d2_"):
            d2out.draw(g, eng, out)
            row.update(status="ok", measured=False, roundtrip="", notes="D2 renders and routes")
        else:
            pl = layout.ENGINES[eng](g, seconds=job["cpsat_seconds"])
            rt = avoidroute.route(g, pl)
            svg = paper.render(g, pl, rt, f"{name}   {eng}   (RTL -> L1 -> bridge -> e3)")
            out.write_text(svg)
            m = measure3.measure(g, pl, rt)
            issues = check.roundtrip(g, d, svg)
            row.update(m)
            row.update(status="ok", measured=True, score=list(measure3.score(m)),
                       roundtrip=len(issues), rt_first=issues[0] if issues else "",
                       notes=" | ".join(pl.notes)[:300])
        png_to(out, OUT / "png" / name / f"{eng}.png")
    except ValueError as e:
        row.update(status="n/a", error=str(e)[:200])
    except Exception as e:  # noqa: BLE001 - the harness records every failure
        tb = traceback.extract_tb(e.__traceback__)[-1]
        row.update(status="error", error=f"{type(e).__name__}: {str(e)[:200]} "
                                         f"@ {Path(tb.filename).name}:{tb.lineno}")
    row["seconds"] = round(time.perf_counter() - t0, 2)
    return row


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=".")
    ap.add_argument("--engines", default=",".join(ENGINES))
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--cpsat-seconds", type=float, default=20.0)
    a = ap.parse_args(argv)
    names = [n for n in DESIGNS if re.search(a.only, n)]
    OUT.mkdir(parents=True, exist_ok=True)
    stages = []
    for n in names:
        try:
            s = bridge_one(n)
        except Exception as e:  # noqa: BLE001
            s = {"design": n, "error": f"{type(e).__name__}: {str(e)[:300]}"}
        stages.append(s)
        print(json.dumps(s, ensure_ascii=False)[:400], flush=True)
    (OUT / "stages.json").write_text(json.dumps(stages, indent=1, ensure_ascii=False))
    ok = [s["design"] for s in stages if "error" not in s and not s["adapter_errors"]]
    jobs = [{"input": n, "engine": e, "cpsat_seconds": a.cpsat_seconds}
            for n in ok for e in a.engines.split(",")]
    with Pool(a.jobs) as pool:
        rows = []
        for r in pool.imap_unordered(draw_one, jobs):
            rows.append(r)
            print(f"  {r['input']:40} {r['engine']:9} {r['status']:6} "
                  f"{r.get('score', r.get('error', ''))} {r['seconds']}s", flush=True)
    rows.sort(key=lambda r: (DESIGNS.index(r["input"]), ENGINES.index(r["engine"])
                             if r["engine"] in ENGINES else 99))
    (OUT / "results.json").write_text(json.dumps(rows, indent=1))
    import pages  # e3's page builders; paths in them are relative to the output folder

    (OUT / "gallery.html").write_text(pages.gallery(rows).replace(
        "e3: paper-figure drawings, all algorithms",
        "x2: real RTL through L1 to paper-figure drawings"))
    (OUT / "blind.html").write_text(pages.blind(rows))
    print(f"{len(rows)} drawings -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
