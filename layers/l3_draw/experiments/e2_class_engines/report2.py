"""Tables and an index page from runs/e2_class_engines/results.json.

    uv run --package rtl2d-l3 python layers/l3_draw/experiments/e2_class_engines/report2.py
Writes summary.md (one table per memo experiment, best engine per input by the class
score, errors) and index.html (every input, every engine side by side).
"""

from __future__ import annotations

import json
from html import escape

from e1lib import RUNS

EXPERIMENTS = {
    "X1 bus bar vs layered (D)": (r"earlgrey|fig_gs_soc|bus_star8|fig_sparse_core",
                                  ["elk", "elk_sep", "grid", "busbar", "rect_root"]),
    "X2 high-degree treatment": (r"earlgrey|fig_gs_soc|bus_star8|wide_block24|uart",
                                 ["elk", "elk_hd"]),
    "X3 per-node algorithms in one ELK call": (r"ibex|deep_hier3|fig_gs_soc|fig_sfu|earlgrey",
                                               ["elk", "elk_sep", "rect_root", "topdown", "auto"]),
    "X5 C-class engines": (
        r"fig_system|fig_sfu|fig_sparse_core|fig_gs_edc|ibex|hmac|plic|deep_hier3",
        ["elk", "elk_sep", "rect_root", "auto", "cpsat"]),
    "X6 CP-SAT grid": (r"comb_dag20|comb_dag40|comb_dag60|earlgrey|bus_star8|fig_system",
                       ["elk", "busbar", "rect_root", "cpsat"]),
    "E arrays": (r"systolic4x4|crossbar4x4|parallel12", ["elk", "auto"]),
    "A/B regression (class engine = ELK)": (
        r"pipe4|pipe8_fwd2|uart|hmac|fanin16|comb_dag20|rv_timer", ["elk", "elk_part", "auto"]),
}
COLS = ["hard", "cross_data", "cross", "bends", "length", "align", "compact", "aspect_err",
        "width", "height", "seconds"]


def load() -> list[dict]:
    return json.loads((RUNS / "results.json").read_text())


def cell(r: dict, k: str):
    v = r.get(k, "")
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def summary(rows: list[dict]) -> str:
    import re

    by = {(r["input"], r["engine"]): r for r in rows}
    out = ["# e2_class_engines: results", ""]
    for title, (rx, engines) in EXPERIMENTS.items():
        names = sorted({r["input"] for r in rows if re.search(rx, r["input"])})
        out += [f"## {title}", "",
                "| input | class | engine | status | " + " | ".join(COLS) + " | score |",
                "|---|---|---|---|" + "---|" * (len(COLS) + 1)]
        wins: dict[str, int] = {}
        for n in names:
            best = None
            for e in engines:
                r = by.get((n, e))
                if not r:
                    continue
                sc = tuple(r["score"]) if r.get("status") == "ok" else None
                if sc is not None and (best is None or sc < best[0]):
                    best = (sc, e)
                out.append(f"| {n} | {r.get('class', '')}/{r.get('expected', '')} | {e} | "
                           f"{r['status']} | " + " | ".join(cell(r, k) for k in COLS)
                           + f" | {r.get('score', r.get('error', ''))} |")
            if best:
                wins[best[1]] = wins.get(best[1], 0) + 1
                out.append(f"| | | **best: {best[1]}** | | " + " | " * (len(COLS)) + " |")
        ranked = sorted(wins.items(), key=lambda x: -x[1])
        out += ["", "Best engine count: " + ", ".join(f"{e} {c}" for e, c in ranked), ""]
    errs = [r for r in rows if r["status"] != "ok"]
    out += ["## Not ok", "", "| input | engine | status | error |", "|---|---|---|---|"]
    out += [f"| {r['input']} | {r['engine']} | {r['status']} | {r.get('error', '')} |"
            for r in errs]
    return "\n".join(out) + "\n"


def index(rows: list[dict]) -> str:
    names = sorted({r["input"] for r in rows})
    engines = []
    for r in rows:
        if r["engine"] not in engines:
            engines.append(r["engine"])
    by = {(r["input"], r["engine"]): r for r in rows}
    parts = ["<!doctype html><meta charset=utf-8><title>e2 class engines</title>"
             "<style>body{font:13px system-ui,sans-serif;margin:16px}figure{display:inline-block;"
             "vertical-align:top;margin:6px;border:1px solid #ccc;padding:4px;max-width:46vw}"
             "img{max-width:100%;max-height:70vh}figcaption{font-size:12px}"
             "h2{border-top:1px solid #ccc;padding-top:8px}</style>",
             "<h1>e2_class_engines: every input, every engine</h1>",
             "<p>Score is the class-specific tuple (smaller is better); hard = violations.</p>"]
    for n in names:
        r0 = next(r for r in rows if r["input"] == n)
        parts.append(f"<h2>{escape(n)} <small>class {r0.get('class', '?')} "
                     f"(expected {r0.get('expected', '?')})</small></h2>")
        for e in engines:
            r = by.get((n, e))
            if not r:
                continue
            if r["status"] != "ok":
                parts.append(f"<figure><figcaption><b>{e}</b>: {r['status']} "
                             f"{escape(str(r.get('error', '')))}</figcaption></figure>")
                continue
            cap = (f"<b>{e}</b> score {r['score']} | hard {r['hard']} cross {r['cross']} "
                   f"bends {r['bends']} len {r['length']} | align {r['align']} compact "
                   f"{r['compact']} | {r['width']}x{r['height']} | rt {r['roundtrip']} | "
                   f"{escape(r.get('notes', ''))}")
            parts.append(f"<figure><img src='svg/{n}/{e}.svg' loading='lazy'>"
                         f"<figcaption>{cap}</figcaption></figure>")
    return "\n".join(parts)


if __name__ == "__main__":
    rows = load()
    (RUNS / "summary.md").write_text(summary(rows))
    (RUNS / "index.html").write_text(index(rows))
    print(RUNS / "summary.md", RUNS / "index.html", len(rows), "rows")
