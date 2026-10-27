"""e3 matrix: paper-figure inputs x layout algorithms other than ELK, one drawing each.

    uv run --package rtl2d-l3 --with nodejs-wheel --with ortools python \\
        layers/l3_draw/experiments/e3_paper_engines/run.py [--only REGEX] [--engines a,b] [--jobs 6]
Output: runs/e3_paper_engines/{results.json,svg/<input>/<engine>.svg,png/<input>/<engine>.png}
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import avoidroute  # noqa: E402
import check  # noqa: E402
import d2out  # noqa: E402
import grammar  # noqa: E402
import layout  # noqa: E402
import measure3  # noqa: E402
import p3lib  # noqa: E402
import paper  # noqa: E402

INPUTS = ["fig_system", "fig_sfu", "fig_gs_soc", "fig_gs_edc", "fig_gs_mac", "fig_sparse_core",
          "earlgrey", "bus_star8", "ibex"]
OWN = list(layout.ENGINES)  # elk cola dot fdp osage hola busbar grid cpsat
D2 = ["d2_dagre", "d2_elk", "d2_tala", "d2_grid"]
ENGINES = OWN + D2
TIMEOUT = 300


def _alarm(_s, _f):
    raise TimeoutError(f"over {TIMEOUT}s")


def png(svg_path: Path) -> None:
    exe = shutil.which("rsvg-convert")
    if exe:
        out = p3lib.RUNS / "png" / svg_path.parent.name / (svg_path.stem + ".png")
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([exe, "-w", "1600", str(svg_path), "-o", str(out)], capture_output=True,
                       timeout=120)


def work(job: dict) -> dict:
    name, eng = job["input"], job["engine"]
    row = {"input": name, "engine": eng}
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TIMEOUT)
    t0 = time.perf_counter()
    out = p3lib.RUNS / "svg" / name / f"{eng}.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        d, _h, s = p3lib.load(name)
        g = grammar.build(name, d, s)
        miss = grammar.check(g, d)
        if miss:
            raise RuntimeError(f"grammar lost {len(miss)} sinks: {miss[0]}")
        row.update(units=sum(1 for n in g.nodes.values() if n.kind in ("leaf", "bar")),
                   containers=len(g.containers()), edges=len(g.edges))
        if eng in D2:
            d2out.draw(g, eng, out)
            row.update(status="ok", measured=False, roundtrip="", notes="D2 renders and routes")
        else:
            pl = layout.ENGINES[eng](g, seconds=job["cpsat_seconds"])
            rt = avoidroute.route(g, pl)
            svg = paper.render(g, pl, rt, f"{name}   {eng}")
            out.write_text(svg)
            m = measure3.measure(g, pl, rt)
            issues = check.roundtrip(g, d, svg)
            row.update(m)
            row.update(status="ok", measured=True, score=list(measure3.score(m)),
                       roundtrip=len(issues), rt_first=issues[0] if issues else "",
                       notes=" | ".join(pl.notes)[:300])
        png(out)
    except ValueError as e:
        row.update(status="n/a", error=str(e)[:200])
    except Exception as e:  # noqa: BLE001 - the harness records every failure
        tb = traceback.extract_tb(e.__traceback__)[-1]
        row.update(status="error", error=f"{type(e).__name__}: {str(e)[:200]} "
                                         f"@ {Path(tb.filename).name}:{tb.lineno}")
    finally:
        signal.alarm(0)
    row["seconds"] = round(time.perf_counter() - t0, 2)
    return row


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=".")
    ap.add_argument("--engines", default=",".join(ENGINES))
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--cpsat-seconds", type=float, default=20.0)
    a = ap.parse_args(argv)
    names = [n for n in INPUTS if re.search(a.only, n)]
    jobs = [{"input": n, "engine": e, "cpsat_seconds": a.cpsat_seconds}
            for n in names for e in a.engines.split(",")]
    p3lib.RUNS.mkdir(parents=True, exist_ok=True)
    print(f"{len(jobs)} jobs")
    t0 = time.perf_counter()
    rows = []
    with Pool(a.jobs) as pool:
        for r in pool.imap_unordered(work, jobs):
            rows.append(r)
            print(f"  {r['input']:16} {r['engine']:9} {r['status']:6} "
                  f"{r.get('score', r.get('error', ''))} {r['seconds']}s", flush=True)
    old = p3lib.RUNS / "results.json"
    if old.exists():
        done = {(r["input"], r["engine"]) for r in rows}
        rows += [r for r in json.loads(old.read_text()) if (r["input"], r["engine"]) not in done]
    rows.sort(key=lambda r: (INPUTS.index(r["input"]) if r["input"] in INPUTS else 99,
                             ENGINES.index(r["engine"]) if r["engine"] in ENGINES else 99))
    old.write_text(json.dumps(rows, indent=1))
    print(f"{len(rows)} rows in {time.perf_counter() - t0:.0f}s -> {old}")


if __name__ == "__main__":
    main(sys.argv[1:])
