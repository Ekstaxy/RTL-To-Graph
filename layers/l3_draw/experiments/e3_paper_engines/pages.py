"""Two pages from runs/e3_paper_engines/results.json:

  gallery.html  every input, every algorithm, named, with its measures
  blind.html    per input the drawings shuffled as A, B, C ...; tick the most paper-like
                one, optionally a second choice and a note; "Copy votes" gives JSON; the
                key is folded at the bottom

    uv run --package rtl2d-l3 python layers/l3_draw/experiments/e3_paper_engines/pages.py
"""

from __future__ import annotations

import json
import random
import sys
from html import escape as esc

from p3lib import RUNS

NAMES = {
    "elk": "ELK layered (reference, same as e1/e2)",
    "cola": "WebCoLa: constraint stress layout with nested groups",
    "dot": "Graphviz dot: layered with clusters",
    "fdp": "Graphviz fdp: force-directed with clusters",
    "osage": "Graphviz osage: cluster packing",
    "hola": "HOLA: human-like orthogonal layout (per container)",
    "busbar": "Bus-bar grammar (e2), per container",
    "grid": "Equal-cell grid rows, per container",
    "cpsat": "CP-SAT grid optimisation, per container",
    "d2_dagre": "D2 + dagre (D2's renderer)",
    "d2_elk": "D2 + ELK (D2's renderer)",
    "d2_tala": "D2 + TALA (D2's renderer, proprietary engine)",
    "d2_grid": "D2 grid containers (D2's renderer)",
}
CSS = ("<meta name=viewport content='width=device-width,initial-scale=1'><style>"
       ":root{--bg:#fff;--fg:#111;--line:#ccc;--mute:#666}"
       "body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;"
       "margin:0 16px}"
       "section{border-top:1px solid var(--line);padding:14px 0}"
       ".row{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:14px}"
       "figure{margin:0;border:1px solid var(--line);padding:6px;background:#fff}"
       "figure img{width:100%;height:auto;display:block;cursor:zoom-in}"
       "figcaption{font-size:13px;color:var(--mute)}figcaption b{color:var(--fg);font-size:16px}"
       "label{cursor:pointer}textarea{width:100%}button{font-size:14px;padding:6px 14px}"
       ".k{font-size:12px;color:var(--mute)}</style>")


def _fig(r: dict, caption: str) -> str:
    n, e = r["input"], r["engine"]
    return (f"<figure><a href='svg/{n}/{e}.svg' target=_blank><img loading=lazy "
            f"src='png/{n}/{e}.png' alt='{esc(n)} {esc(e)}'></a><figcaption>{caption}"
            f"</figcaption></figure>")


def _meas(r: dict) -> str:
    if not r.get("measured"):
        return "<span class=k>D2 draws and routes itself; not measured</span>"
    return (f"<span class=k>hard {r['hard']} · crossings {r['cross']} · bends {r['bends']} · "
            f"align {r['align']} · compact {r['compact']} · {r['width']}×{r['height']} px · "
            f"check {r['roundtrip']} · {r['seconds']} s</span>")


def gallery(rows: list[dict]) -> str:
    parts = ["<!doctype html><meta charset=utf-8><title>Paper Engines Gallery</title>", CSS,
             "<h1>e3: paper-figure drawings, all algorithms</h1>",
             "<p>Same input, same paper style, same router (libavoid) for every algorithm except "
             "the four D2 ones, which use D2's own drawing. Click a picture for the full SVG.</p>"]
    for n in dict.fromkeys(r["input"] for r in rows):
        rs = [r for r in rows if r["input"] == n]
        info = next((r for r in rs if "units" in r), {})
        parts.append(f"<section><h2>{esc(n)} <small class=k>{info.get('units', '?')} units, "
                     f"{info.get('containers', '?')} containers, {info.get('edges', '?')} arrows"
                     f"</small></h2><div class=row>")
        for r in rs:
            if r["status"] != "ok":
                parts.append(f"<figure><figcaption><b>{r['engine']}</b> {r['status']}: "
                             f"{esc(str(r.get('error', '')))}</figcaption></figure>")
                continue
            parts.append(_fig(r, f"<b>{r['engine']}</b> {esc(NAMES.get(r['engine'], ''))}<br>"
                                 f"{_meas(r)}"))
        parts.append("</div></section>")
    return "\n".join(parts)


def blind(rows: list[dict], seed: int = 20261011) -> str:
    rng = random.Random(seed)
    parts = ["<!doctype html><meta charset=utf-8><title>Blind Paper Figures</title>", CSS,
             "<h1>Which drawing looks most like a paper figure?</h1>",
             "<p>For each input the drawings are shuffled and labelled. Tick your <b>first</b> "
             "choice (and a second if you like), add a note, then press <b>Copy votes</b> at the "
             "bottom and paste the JSON back. Open the key only after voting.</p>"]
    key = []
    for n in dict.fromkeys(r["input"] for r in rows):
        rs = [r for r in rows if r["input"] == n and r["status"] == "ok"]
        rng.shuffle(rs)
        labels = [chr(65 + i) for i in range(len(rs))]
        key.append(f"<li><b>{esc(n)}</b>: " + ", ".join(f"{lb}={r['engine']}"
                                                         for lb, r in zip(labels, rs, strict=True))
                   + "</li>")
        cells = "".join(_fig(r, f"<b>{lb}</b> &nbsp; <label><input type=radio name='1:{esc(n)}' "
                                f"value='{lb}'> first</label> &nbsp; <label><input type=radio "
                                f"name='2:{esc(n)}' value='{lb}'> second</label>")
                        for lb, r in zip(labels, rs, strict=True))
        parts.append(f"<section data-input='{esc(n)}'><h2>{esc(n)}</h2><div class=row>{cells}"
                     f"</div><p><textarea rows=2 placeholder='note (optional)'></textarea></p>"
                     f"</section>")
    parts.append("<p><button onclick='collect()'>Copy votes</button></p>"
                 "<textarea id=out rows=8></textarea>"
                 "<script>function collect(){const v={};document.querySelectorAll('section')"
                 ".forEach(s=>{const n=s.dataset.input;"
                 "const a=s.querySelector(`input[name='1:${n}']"
                 ":checked`),b=s.querySelector(`input[name='2:${n}']:checked`),t=s.querySelector"
                 "('textarea').value;v[n]={first:a?a.value:null,second:b?b.value:null,note:t};});"
                 "const j=JSON.stringify(v,null,1);document.getElementById('out').value=j;"
                 "if(navigator.clipboard)navigator.clipboard.writeText(j);}</script>")
    parts.append("<details><summary>Key (open after voting)</summary><ul>" + "".join(key)
                 + "</ul><p>" + "<br>".join(f"<b>{k}</b>: {esc(v)}" for k, v in NAMES.items())
                 + "</p></details>")
    return "\n".join(parts)


if __name__ == "__main__":
    rows = json.loads((RUNS / "results.json").read_text())
    (RUNS / "gallery.html").write_text(gallery(rows))
    (RUNS / "blind.html").write_text(blind(rows))
    print(RUNS / "gallery.html", RUNS / "blind.html", file=sys.stdout)
