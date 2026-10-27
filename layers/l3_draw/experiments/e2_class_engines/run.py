"""The e2 matrix: every input x every engine, one drawing each, scored per class.

    uv run --package rtl2d-l3 --with nodejs-wheel --with ortools python \\
        layers/l3_draw/experiments/e2_class_engines/run.py [--only REGEX] [--engines a,b]
        [--jobs 8] [--cpsat-seconds 30]
Output: runs/e2_class_engines/{results.csv,results.json,svg/<input>/<engine>.svg}

Engines (the memo's experiments map onto subsets of this matrix, see README):
  elk        e1 baseline  elk+native+we+implicit  (through e1's draw)
  elk_part   e1           elk_part+native+we+implicit (n/a without stage hints)
  elk_hd     elkx         layered + highDegreeNodes.treatment            X2
  elk_sep    elkx         layered, SEPARATE_CHILDREN                     X5
  rect_root  elkx         root rectpacking, containers layered           X3
  topdown    elkx         root rectpacking, top-down layout (probe)      X3
  grid       compose      D levels: rows of equal cells, no bar          X1 control
  busbar     compose      D levels: bus bars; E: arrays; rest ELK        X1
  auto       compose      the full class map (busbar / arrays / elk)     X1, E
  cpsat      compose      C and D levels: CP-SAT grid; rest ELK          X6
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import signal
import sys
import time
import traceback
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import classify  # noqa: E402
import compose  # noqa: E402
import e1lib  # noqa: E402  (sys.path for e0/e1)
import elkx  # noqa: E402
import inputs  # noqa: E402
import metrics2  # noqa: E402
from e1lib import E1, RUNS, Scene, measure, render, roundtrip  # noqa: E402

_spec = importlib.util.spec_from_file_location("e1run", E1 / "run.py")
e1run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e1run)

TIMEOUT = 240
ENGINES = ["elk", "elk_part", "elk_hd", "elk_sep", "rect_root", "topdown", "grid", "busbar",
           "auto", "cpsat"]
COMPOSE_MAPS = {
    "grid": {"D": "grid", "E": "elk"},
    "busbar": {"D": "busbar", "E": "elk"},
    "auto": {},
    "cpsat": {"C": "cpsat", "D": "cpsat", "E": "elk"},
}


def draw_one(name: str, engine: str, cpsat_seconds: float = 30.0):
    """Returns (svg, metrics dict incl. class scores, roundtrip issues, notes)."""
    d, h, s = inputs.load(name)
    title = f"{name}   {engine}"
    if engine in ("elk", "elk_part"):
        combo = f"{engine}+native+we+implicit"
        svg, m, rt = e1run.draw(d, h, combo, canon=True, title=title)
        sc = Scene(d, h, sides="we", pres="implicit", canon=True)
        lay = e1lib.ext.place_elk(sc, engine, native=True)  # for the extra metrics
        m.update(metrics2.extra(sc, lay))
        notes = []
    elif engine in elkx.VARIANTS:
        sc = Scene(d, h, sides="we", pres="implicit", canon=True)
        compose.apply_replicate(sc, s)
        lay = elkx.place(sc, engine)
        svg = compose.stack_shadows(render(sc, lay, title), sc, s)
        m = measure(sc, lay)
        m.update(metrics2.extra(sc, lay))
        rt = roundtrip(sc, svg)
        notes = lay.notes
    else:
        svg, m, rt, lay, sc = compose.draw(d, h, s, COMPOSE_MAPS[engine], title=title,
                                           cpsat_seconds=cpsat_seconds)
        m.update(metrics2.extra(sc, lay))
        notes = lay.notes
    root_cls = classify.classify(d, s)[""]["class"]
    m["class"] = root_cls
    m["expected"] = s.get("expected", {}).get("", "?")
    m["score"] = metrics2.score_for(root_cls, m)
    m["score_e1"] = e1lib.score(m)
    return svg, m, rt, notes


def _alarm(_s, _f):
    raise TimeoutError(f"over {TIMEOUT}s")


def work(job: dict) -> dict:
    name, engine = job["input"], job["engine"]
    row = {"input": name, "engine": engine}
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TIMEOUT)
    t0 = time.perf_counter()
    try:
        svg, m, rt, notes = draw_one(name, engine, job["cpsat_seconds"])
        row.update({k: v for k, v in m.items() if not isinstance(v, dict)})
        row.update(status="ok", roundtrip=len(rt), rt_first=rt[0] if rt else "",
                   notes=" | ".join(notes)[:300])
        p = RUNS / "svg" / name / f"{engine}.svg"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(svg)
    except ValueError as e:
        row.update(status="n/a", error=str(e)[:200])
    except Exception as e:  # noqa: BLE001 - the harness records every failure
        tb = traceback.extract_tb(e.__traceback__)[-1]
        row.update(status="error",
                   error=f"{type(e).__name__}: {str(e)[:160]} "
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
    ap.add_argument("--cpsat-seconds", type=float, default=30.0)
    ap.add_argument("--merge", action="store_true",
                    help="keep rows of an earlier results.json that this run does not redo")
    a = ap.parse_args(argv)
    names = inputs.write_all()
    names = [n for n in names if re.search(a.only, n)]
    engines = a.engines.split(",")
    jobs = [{"input": n, "engine": e, "cpsat_seconds": a.cpsat_seconds}
            for n in names for e in engines]
    print(f"{len(jobs)} jobs on {len(names)} inputs x {len(engines)} engines")
    t0 = time.perf_counter()
    with Pool(a.jobs) as pool:
        rows = []
        for r in pool.imap_unordered(work, jobs):
            rows.append(r)
            print(f"  {r['input']:16} {r['engine']:10} {r['status']:6} "
                  f"{r.get('score', r.get('error', ''))} {r['seconds']}s", flush=True)
    if a.merge and (RUNS / "results.json").exists():
        done = {(r["input"], r["engine"]) for r in rows}
        old = json.loads((RUNS / "results.json").read_text())
        rows += [r for r in old if (r["input"], r["engine"]) not in done]
    rows.sort(key=lambda r: (r["input"], ENGINES.index(r["engine"])
                             if r["engine"] in ENGINES else 99))
    RUNS.mkdir(parents=True, exist_ok=True)
    first = ("input", "engine", "status")
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in first, k))
    with (RUNS / "results.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, tuple | list) else v)
                        for k, v in r.items()})
    (RUNS / "results.json").write_text(json.dumps(rows, indent=1, default=list))
    print(f"{len(rows)} rows in {time.perf_counter() - t0:.0f}s -> {RUNS / 'results.csv'}")


if __name__ == "__main__":
    main(sys.argv[1:])
