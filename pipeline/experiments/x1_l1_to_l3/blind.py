"""Blind side-by-side page: for one test design per category (plus the CPU indicator), the
three renderings in a shuffled order labelled A/B/C. The key is folded away at the bottom.

    python pipeline/experiments/x1_l1_to_l3/blind.py v6   -> runs/x1eval/v6/blind.html
"""

import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RENDERERS = ["paper", "elk_part", "elk_r12"]
SPLITS = ("test", "indicator")


def inline(svg: str) -> str:
    svg = re.sub(r"<\?xml[^>]*>", "", svg)
    size = r'<svg([^>]*?) width="[^"]*" height="[^"]*"'
    return re.sub(size, r'<svg\1 width="100%"', svg, count=1)


def main(version: str, splits=SPLITS, renderers=None, tag: str = "blind") -> None:
    renderers = renderers or RENDERERS
    base = ROOT / "runs/x1eval" / version
    rows = []
    for split in splits:
        rs = json.loads((base / split / "results.json").read_text(encoding="utf-8"))
        ok = {(r["design"], r["renderer"]) for r in rs if r["status"] == "ok"}
        seen = set()
        for r in sorted(rs, key=lambda r: (r["category"], r["design"])):
            c, d = r["category"], r["design"]
            key = d if split == "fresh" else c
            if key in seen or not all((d, x) in ok for x in renderers):
                continue
            seen.add(key)
            rows.append((split, c, d))
    rng = random.Random(20261009)
    key, parts = [], []
    for split, c, d in rows:
        order = list(renderers)
        rng.shuffle(order)
        key.append(
            f"<li>{d}: " + ", ".join(f"{'ABC'[i]}={r}" for i, r in enumerate(order)) + "</li>"
        )
        cells = "".join(
            f"<figure><figcaption>{'ABC'[i]}</figcaption>"
            f"{inline((base / split / f'{d}.{r}.svg').read_text(encoding='utf-8'))}</figure>"
            for i, r in enumerate(order)
        )
        parts.append(
            f"<section><h2>{c}: {d}</h2><p>Which is easiest to read? Note A/B/C.</p>"
            f"<div class='row'>{cells}</div></section>"
        )
    html = (
        "<!doctype html><meta charset=utf-8><title>Blind Diagram Comparison</title>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<style>:root{--bg:#fff;--fg:#111;--line:#ccc}"
        "@media (prefers-color-scheme: dark){:root:not([data-theme=light]){--bg:#fff;--fg:#111}}"
        "body{background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;"
        "margin:0 16px}section{border-top:1px solid var(--line);padding:12px 0}"
        ".row{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}"
        "figure{margin:0;border:1px solid var(--line);padding:4px;overflow:auto}"
        "figcaption{font-weight:700;font-size:18px}</style>"
        "<h1>Blind diagram comparison</h1><p>One held-out design per category plus our CPU. "
        "Three renderers each, shuffled per design. Decide before opening the key.</p>"
        + "".join(parts)
        + "<details><summary>Key</summary><ul>"
        + "".join(key)
        + "</ul></details>"
    )
    out = base / f"{tag}.html"
    out.write_text(html, encoding="utf-8")
    print(out, len(rows), "designs")


if __name__ == "__main__":
    # blind.py VERSION [split,...] [renderer,...] [tag]
    a = sys.argv[1:]
    main(
        a[0],
        tuple(a[1].split(",")) if len(a) > 1 else SPLITS,
        a[2].split(",") if len(a) > 2 else None,
        a[3] if len(a) > 3 else "blind",
    )
