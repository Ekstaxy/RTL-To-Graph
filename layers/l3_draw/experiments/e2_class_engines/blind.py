"""Blind side-by-side page: per input, the candidate drawings in a shuffled order labelled
A, B, C ..., a radio button per section, a button that copies all votes as JSON, and the
key folded away at the bottom. Same mechanics as x1's blind.py; votes go into
results/votes_<who>.json by hand.

    uv run --package rtl2d-l3 python layers/l3_draw/experiments/e2_class_engines/blind.py \\
        [--inputs REGEX] [--engines elk,busbar,...] [--seed N] [--tag blind]
"""

from __future__ import annotations

import argparse
import json
import random
import re
from html import escape

from e1lib import RUNS

DEFAULT = {
    "D": ["elk", "elk_sep", "grid", "busbar", "rect_root"],
    "C": ["elk", "elk_sep", "rect_root", "auto", "cpsat"],
    "E": ["elk", "auto"],
    "A": ["elk", "auto", "cpsat"],
    "B": ["elk", "elk_part", "auto"],
}


def inline(svg: str) -> str:
    svg = re.sub(r"<\?xml[^>]*>", "", svg)
    return re.sub(r'<svg([^>]*?) width="[^"]*" height="[^"]*"', r'<svg\1 width="100%"', svg,
                  count=1)


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default=".")
    ap.add_argument("--engines", default="")
    ap.add_argument("--seed", type=int, default=20261010)
    ap.add_argument("--tag", default="blind")
    a = ap.parse_args(argv)
    rows = json.loads((RUNS / "results.json").read_text())
    ok = {(r["input"], r["engine"]): r for r in rows if r["status"] == "ok"}
    names = sorted({r["input"] for r in rows if re.search(a.inputs, r["input"])})
    rng = random.Random(a.seed)
    key, parts = [], []
    for n in names:
        cls = next(r for r in rows if r["input"] == n).get("class", "C")
        engines = a.engines.split(",") if a.engines else DEFAULT.get(cls, DEFAULT["C"])
        engines = [e for e in engines if (n, e) in ok]
        if len(engines) < 2:
            continue
        order = list(engines)
        rng.shuffle(order)
        labels = [chr(65 + i) for i in range(len(order))]
        pairs = ", ".join(f"{lb}={e}" for lb, e in zip(labels, order, strict=True))
        key.append(f"<li>{escape(n)}: {pairs}</li>")
        cells = ""
        for lb, e in zip(labels, order, strict=True):
            svg = inline((RUNS / "svg" / n / f"{e}.svg").read_text())
            cells += (f"<figure><figcaption><label><input type=radio name='{escape(n)}' "
                      f"value='{lb}'> {lb}</label></figcaption>{svg}</figure>")
        parts.append(f"<section data-input='{escape(n)}'><h2>{escape(n)} "
                     f"<small>class {cls}</small></h2><p>Which is easiest to read? Tick one.</p>"
                     f"<div class=row>{cells}</div></section>")
    html = (
        "<!doctype html><meta charset=utf-8><title>Blind Diagram Comparison</title>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<style>:root{--bg:#fff;--fg:#111;--line:#ccc}"
        "body{background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;"
        "margin:0 16px}"
        "section{border-top:1px solid var(--line);padding:12px 0}"
        ".row{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:12px}"
        "figure{margin:0;border:1px solid var(--line);padding:4px;overflow:auto;max-height:80vh}"
        "figcaption{font-weight:700;font-size:18px}button{font-size:14px;padding:6px 12px}"
        "#out{width:100%;height:120px}</style>"
        "<h1>Blind diagram comparison (e2_class_engines)</h1>"
        "<p>Per input, the candidate renderings in a shuffled order. Tick the one that is "
        "easiest to read, then press the button and paste the JSON into "
        "results/votes_&lt;you&gt;.json. Decide before opening the key.</p>"
        + "".join(parts)
        + "<p><button onclick='collect()'>Copy votes as JSON</button></p>"
        "<textarea id=out></textarea>"
        "<script>function collect(){const v={};"
        "document.querySelectorAll('section').forEach(s=>{"
        "const c=s.querySelector('input:checked');if(c)v[s.dataset.input]=c.value;});"
        "const t=JSON.stringify(v,null,1);document.getElementById('out').value=t;"
        "if(navigator.clipboard)navigator.clipboard.writeText(t);}</script>"
        "<details><summary>Key (open after voting)</summary><ul>"
        + "".join(key) + "</ul></details>"
    )
    out = RUNS / f"{a.tag}.html"
    out.write_text(html)
    print(out, len(parts), "inputs")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
