"""Run the layout matrix: inputs x (placer + router + port sides + presentation).

Tier a: every combination on the base variant of every seed.
Tier b: a short list of combinations on every input variant, plus hint variants and the
        input-order check.
Tier c: invalid inputs must be refused.

Run (from the repo root; --with adds Node for ELK without touching pyproject):
  uv run --package rtl2d-l3 --with nodejs-wheel python \
      layers/l3_draw/experiments/e1_layout_matrix/run.py --tier all
Output: runs/e1_layout_matrix/{results_a.csv,results_b.csv,results_c.csv,svg/}
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import signal
import sys
import time
import traceback
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ext  # noqa: E402
import spec  # noqa: E402  (made importable by model)
from metrics import measure, score  # noqa: E402
from model import Layout, Scene  # noqa: E402
from place import PLACERS, place  # noqa: E402
from render import render, roundtrip  # noqa: E402
from route import ROUTERS  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
INPUTS = ROOT / "runs" / "e0_reference_inputs" / "inputs"
OUT = ROOT / "runs" / "e1_layout_matrix"
SIDES = ("we", "ctl_n")
PRES = ("wires", "implicit", "stubs")
TIMEOUT = 120


def combos() -> list[str]:
    have = ext.available()
    pr = [(p, r) for p in PLACERS for r in ROUTERS]
    if have["elk"]:
        pr += [(v, r) for v in ext.ELK_VARIANTS for r in ("native", "astar_cls")]
    if have["dot"]:
        pr += [("dot", r) for r in ("naive", "astar_cls")]
    return [f"{p}+{r}+{s}+{v}" for p, r in pr for s in SIDES for v in PRES]


SHORTLIST = [
    "lay+naive+we+wires",
    "lay+astar_cls+we+wires",
    "lay_ctl+astar_cls2+we+implicit",
    "lay_ctl+astar_cls2+ctl_n+stubs",
    "grid+astar_cls2+we+implicit",
    "elk+native+we+wires",
    "elk+native+we+implicit",
    "elk_part+native+we+implicit",
    "dot+astar_cls+we+wires",
]


class Refused(Exception):
    """The input failed validation; nothing is drawn."""


def draw(d: spec.Diagram, hints: dict, combo: str, canon: bool = False, title: str = ""):
    """One drawing. Returns (svg, metrics, round-trip issues). Refuses invalid input."""
    issues = spec.validate(d)
    if issues:
        raise Refused("; ".join(issues[:3]))
    placer, router, sides, pres = combo.split("+")
    sc = Scene(d, hints, sides=sides, pres=pres, canon=canon)
    lay: Layout
    if placer in PLACERS:
        lay = place(sc, **PLACERS[placer])
    elif placer == "dot":
        lay = ext.place_dot(sc)
    else:
        lay = ext.place_elk(sc, placer, native=router == "native")
    if router != "native":
        ROUTERS[router](sc, lay)
    svg = render(sc, lay, title)
    m = measure(sc, lay)
    m["hidden_nets"] = len(sc.hidden)
    return svg, m, roundtrip(sc, svg)


def _alarm(_sig, _frm):
    raise TimeoutError(f"over {TIMEOUT}s")


def work(job: dict) -> dict:
    row = {k: job[k] for k in ("tier", "input", "seed", "variant", "hints", "canon", "combo")}
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TIMEOUT)
    t0 = time.perf_counter()
    try:
        d = spec.Diagram.model_validate_json(Path(job["path"]).read_text())
        svg, m, rt = draw(d, job["hint_data"], job["combo"], job["canon"],
                          f'{job["input"]}   {job["combo"]}')
        row.update(m)
        row.update(status="ok", roundtrip=len(rt), rt_first=rt[0] if rt else "",
                   blocks=len(d.blocks), nets=len(d.nets))
        if job.get("svg"):
            path = Path(job["svg"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(svg)
        if job.get("keep_svg"):
            row["_svg"] = svg
    except Refused as e:
        row.update(status="refused", error=str(e)[:200])
    except ValueError as e:
        row.update(status="n/a", error=str(e)[:200])
    except Exception as e:  # noqa: BLE001 - an experiment harness records every failure
        tb = traceback.extract_tb(e.__traceback__)[-1]
        where = f"{Path(tb.filename).name}:{tb.lineno}"
        row.update(status="error", error=f"{type(e).__name__}: {str(e)[:160]} @ {where}")
    finally:
        signal.alarm(0)
    row["seconds"] = round(time.perf_counter() - t0, 3)
    return row


def load_hints(seed: str) -> dict:
    p = INPUTS / "hints" / f"{seed}.hints.json"
    return json.loads(p.read_text()) if p.exists() else {"blocks": {}, "sinks": {}}


def hint_variant(h: dict, how: str) -> dict:
    """full: as given. none: empty. partial: every second block. wrong: stages reversed."""
    if how == "full":
        return h
    if how == "none":
        return {"blocks": {}, "sinks": {}}
    blocks = dict(sorted(h.get("blocks", {}).items()))
    if how == "partial":
        return {"blocks": dict(list(blocks.items())[::2]), "sinks": {}}
    hi = max([v.get("stage_index", v.get("stage_boundary", 0)) for v in blocks.values()] or [0])
    wrong = {}
    for k, v in blocks.items():
        v = dict(v)
        for f in ("stage_index", "stage_boundary"):
            if f in v:
                v[f] = hi - v[f]
        wrong[k] = v
    return {"blocks": wrong, "sinks": {}}


def jobs_for(tier: str, pattern: str) -> list[dict]:
    files = sorted((INPUTS / "valid").glob("*.diagram.json"))
    jobs = []

    def add(path: Path, combo: str, hints: str = "full", canon: bool = False, **kw) -> None:
        name = path.name.removesuffix(".diagram.json")
        seed, variant = name.split("__")
        if not re.search(pattern, name):
            return
        jobs.append(dict(tier=tier, input=name, seed=seed, variant=variant, hints=hints,
                         canon=canon, combo=combo, path=str(path),
                         hint_data=hint_variant(load_hints(seed), hints), **kw))

    if tier == "a":
        for f in files:
            if f.name.endswith("__base.diagram.json"):
                seed = f.name.split("__")[0]
                for c in combos():
                    add(f, c, svg=str(OUT / "svg" / seed / f"{c}.svg"))
    elif tier == "b":
        have = set(combos())
        short = [c for c in SHORTLIST if c in have]
        for f in files:
            for c in short:
                add(f, c)
            if f.name.endswith("__base.diagram.json") or f.name.endswith("__shuffled.diagram.json"):
                for c in short:  # input-order check: same drawing with and without sorting
                    add(f, c, canon=True, keep_svg=True)
                    add(f, c, hints="full", canon=False, keep_svg=True, dup=True)
            if f.name.endswith("__base.diagram.json"):
                for how in ("none", "partial", "wrong"):
                    for c in short:
                        if c.split("+")[0] in ("grid", "elk_part", "lay_ctl"):
                            add(f, c, hints=how)
    elif tier == "c":
        for f in sorted((INPUTS / "invalid").glob("*.diagram.json")):
            name = f.name.removesuffix(".diagram.json")
            if re.search(pattern, name):
                seed, variant = name.split("__")
                jobs.append(dict(tier=tier, input=name, seed=seed, variant=variant, hints="full",
                                 canon=False, combo="lay+naive+we+wires", path=str(f),
                                 hint_data={}))
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="a", choices=["a", "b", "c", "all"])
    ap.add_argument("--only", default=".", help="regex on the input name")
    ap.add_argument("--jobs", type=int, default=24)
    args = ap.parse_args()
    print("engines:", ext.available(), " combinations:", len(combos()))
    for tier in ("a", "b", "c") if args.tier == "all" else (args.tier,):
        jobs = jobs_for(tier, args.only)
        t0 = time.perf_counter()
        with Pool(args.jobs, maxtasksperchild=200) as pool:
            rows = list(pool.imap_unordered(work, jobs, chunksize=4))
        rows.sort(key=lambda r: (r["input"], r["combo"], r["hints"], r["canon"]))
        if tier == "b":  # collapse the input-order check into a per-row flag
            svgs: dict[tuple, dict[str, str]] = {}
            for r in rows:
                if "_svg" in r:
                    key = (r["seed"], r["combo"], r["canon"])
                    svgs.setdefault(key, {})[r["variant"]] = r["_svg"]
            for r in rows:
                pair = svgs.get((r["seed"], r["combo"], r["canon"]), {})
                if "_svg" in r and len(pair) == 2:
                    a, b = (re.sub(r"<text[^>]*fill=\"#666\">.*?</text>", "", s)
                            for s in (pair["base"], pair["shuffled"]))
                    r["same_as_shuffled"] = int(a == b)
                r.pop("_svg", None)
        cols = sorted({k for r in rows for k in r}, key=lambda k: (k not in (
            "tier", "input", "seed", "variant", "hints", "canon", "combo", "status"), k))
        OUT.mkdir(parents=True, exist_ok=True)
        with (OUT / f"results_{tier}.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        by = {}
        for r in rows:
            by[r["status"]] = by.get(r["status"], 0) + 1
        ok = [r for r in rows if r["status"] == "ok"]
        clean = sum(1 for r in ok if score(r)[0] == 0)
        print(f"tier {tier}: {len(rows)} runs in {time.perf_counter() - t0:.0f}s  {by}  "
              f"no hard violation: {clean}/{len(ok)}  round-trip failures: "
              f"{sum(1 for r in ok if r['roundtrip'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
