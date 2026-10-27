"""Build the x3 pages: self-contained HTML (every SVG embedded) that puts our drawings next
to every external tool's drawing of the same RTL.

    uv run --no-project python pipeline/experiments/x3_tool_compare/gallery.py [--set NAME|all]
      top       -> runs/x3_tool_compare/index.html        top modules, each tool's default
      module    -> runs/x3_tool_compare/module-like.html  one leaf module per SoC
      recompare -> runs/x3_tool_compare/recompare.html    top modules, each tool's most minimal
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "runs" / "x3_tool_compare"
YOSYS = ROOT / "runs" / ".tools" / "x3" / "oss-cad-suite" / "bin" / "yosys"
E = html.escape


BIG = 1.5e6  # bytes; larger SVGs are embedded as a PNG preview to keep each page under 16 MB


def data_uri(rel: str) -> str:
    src = ROOT / rel.lstrip("/")
    if src.stat().st_size <= BIG:
        return "data:image/svg+xml;base64," + base64.b64encode(src.read_bytes()).decode()
    png = OUT / "preview" / src.relative_to(OUT).with_suffix(".png")
    if not png.exists() or png.stat().st_mtime < src.stat().st_mtime:
        png.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["rsvg-convert", "-w", "3000", "-b", "white", src, "-o", png],
                       check=True)
    return "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode()


def svg_size(rel: str) -> str:
    n = (ROOT / rel.lstrip("/")).stat().st_size
    kb = n / 1024
    s = f"{kb:,.0f} KB" if kb < 1024 else f"{kb / 1024:,.1f} MB"
    return s + (" SVG, shown as PNG" if n > BIG else "")


def chip(text: str, cls: str = "") -> str:
    return f'<span class="chip {cls}">{E(text)}</span>'


def shot(tool: dict, row: dict, design: str, key: str, caption: str = "") -> str:
    alt = f"{tool['name']} drawing of {design}" + (f" ({caption.lower()})" if caption else "")
    cap = f'<figcaption>{E(caption)} · {svg_size(row["svg"])}</figcaption>' if caption else ""
    return (f'<figure><button class="shot" type="button" aria-label="Open {E(alt)} full size">'
            f'<img id="img-{key}" src="{data_uri(row["svg"])}" alt="{E(alt)}" '
            f'decoding="async"></button>{cap}</figure>')


def compare_card(tool: dict, before: dict | None, after: dict | None, design: str) -> str:
    """recompare.html: the tool's default drawing beside its most-minimal one."""
    tid, mn = tool["id"], tool.get("minimal", {})
    head = (f'<header><h3>{E(tool["name"])}</h3>'
            f'<p class="level">{E(mn.get("effect") or tool.get("draws", ""))}</p></header>')
    if after is None:
        return (f'<article class="card" id="{tid}-{design}">{head}'
                f'<div class="fail">Not run</div></article>')
    if after.get("unchanged"):
        if after.get("svg"):
            body = shot(tool, after, design, f"{tid}-{design}")
        else:
            body = (f'<div class="fail"><b>Failed</b>'
                    f'<pre>{E(after.get("error", "")[-900:])}</pre></div>')
        status = chip("no option of its own") + chip("same drawing as before")
        why = mn.get("none", "No simplification option found.")
        facts = f"<dt>Why unchanged</dt><dd>{E(why)}</dd>"
        more = ""
    else:
        pair = []
        if before and before.get("svg"):
            pair.append(shot(tool, before, design, f"{tid}-{design}-before", "Default"))
        else:
            pair.append('<figure><div class="fail small"><b>Default failed</b></div>'
                        '<figcaption>Default</figcaption></figure>')
        if after["status"] == "ok":
            pair.append(shot(tool, after, design, f"{tid}-{design}", "Most minimal"))
        else:
            pair.append(f'<figure><div class="fail small"><b>Failed</b>'
                        f'<pre>{E(after.get("error", "")[-600:])}</pre></div>'
                        f'<figcaption>Most minimal</figcaption></figure>')
        body = f'<div class="pair">{"".join(pair)}</div>'
        ok = after["status"] == "ok"
        status = chip("simplified" if ok else "failed", "ok" if ok else "bad")
        if after.get("seconds") is not None:
            status += chip(f"{after['seconds']} s", "num")
        nums = mn.get("per_design", {}).get(design, "")
        facts = (f"<dt>Option</dt><dd>{E(mn.get('option', ''))}</dd>"
                 + (f"<dt>Size</dt><dd>{E(nums)}</dd>" if nums else "")
                 + f"<dt>Offered by</dt><dd>{E(mn.get('evidence', ''))}</dd>")
        more = (f'<details><summary>How it was run</summary>'
                f'<code>{E(mn.get("recipe", ""))}</code>'
                + (f'<p class="note">{E(mn["caveats"])}</p>' if mn.get("caveats") else "")
                + "</details>")
    return (f'<article class="card" id="{tid}-{design}">{head}{body}'
            f'<div class="status">{status}</div><dl>{facts}</dl>{more}</article>')


def card(tool: dict, row: dict | None, design: str, ours: bool = False,
         page: str = "top") -> str:
    tid = tool["id"]
    recipe = tool.get("recipe", "")
    mode = ""
    if page == "module" and not ours and row:
        mm = tool.get("module_minimal") or tool.get("minimal") or {}
        if row.get("mode") == "minimal":
            mode = f"Minimal: {mm.get('option', '')}"
            recipe = mm.get("recipe", recipe)
        else:
            mode = "Default, already its most minimal view. " + mm.get("none", "")
    head = (f'<header><h3>{E(tool["name"])}</h3>'
            f'<p class="level">{E(tool.get("draws", ""))}</p></header>')
    if row is None:
        body = '<div class="fail"><b>Not run</b></div>'
    elif row["status"] == "ok":
        body = shot(tool, row, design, f"{tid}-{design}")
    else:
        body = (f'<div class="fail"><b>{E(tool.get("fail_title", "Failed"))}</b>'
                f'<pre>{E(row.get("error", "")[-900:])}</pre></div>')
    facts = []
    if ours:
        x2 = row.get("x2", {}) if row else {}
        facts.append(f"<dt>Why this engine</dt><dd>{E(tool['why'])}</dd>")
        if x2:
            facts.append(f"<dt>x2 measure</dt><dd>{x2.get('units')} units · {x2.get('edges')} "
                         f"edges · {x2.get('cross')} crossings · {x2.get('bends')} bends · "
                         f"{x2.get('width')}×{x2.get('height')} px</dd>")
    else:
        facts.append(f"<dt>Layout</dt><dd>{E(tool['layout'])}</dd>")
        facts.append(f"<dt>Input</dt><dd>{E(tool['input'])}</dd>")
        facts.append(f"<dt>License</dt><dd>{E(tool['license'])} · {E(tool['lang'])}</dd>")
        if tool.get("version"):
            facts.append(f"<dt>Version</dt><dd>{E(tool['version'])}</dd>")
        if mode:
            facts.insert(0, f"<dt>Mode</dt><dd>{E(mode)}</dd>")
    status = ""
    if row:
        ok = row["status"] == "ok"
        status = chip("drawn" if ok else "failed", "ok" if ok else "bad")
        if row.get("seconds") is not None:
            status += chip(f"{row['seconds']} s", "num")
        if ok:
            status += chip(svg_size(row["svg"]), "num")
    more = ""
    if not ours:
        dev = (f'<p class="dev"><b>Deviation from the tool’s default:</b> '
               f'{E(tool["deviation"])}</p>') if tool.get("deviation") else ""
        note = f'<p class="note">{E(tool["note"])}</p>' if tool.get("note") else ""
        more = (f'<details><summary>How it was run</summary><code>{E(recipe)}</code>'
                f'{dev}{note}</details>')
    cls = "card ours" if ours else "card"
    return (f'<article class="{cls}" id="{tid}-{design}">{head}{body}'
            f'<div class="status">{status}</div><dl>{"".join(facts)}</dl>{more}</article>')


PAGES = {
    "top": dict(
        file="index.html", results="results.json", designs="designs.json",
        title="RTL Diagram Tool Shootout", h1="RTL diagram tool shootout",
        lede="The same Verilog went through rtl2diagram (L1 → L3, from x2) and through {n_run} "
             "external RTL-to-diagram tools, each run the way its own source or README runs it. "
             "{n_skip} tools from the survey were skipped; the table says why. Click any drawing "
             "for full size.",
        ours="Ours: runs/x2_l1_to_paper"),
    "module": dict(
        file="module-like.html", results="results_module.json", designs="designs_module.json",
        title="Module-Level Tool Shootout", h1="Module-level tool shootout",
        lede="The lowest module of one file from each SoC, a leaf with no child instances: "
             "spimemio_xfer (spimemio.v) and darkuart (darkuart.v). Ours and every tool read only "
             "that file. Each of the {n_run} tools runs in its most minimal mode that still draws "
             "the module's structure, and none flattens or lowers it (no flatten, techmap or AIG). "
             "Ours runs x2's L1 → bridge → e3 path. Click any drawing for full size.",
        ours="Ours: ours_modules.py (x2 path)"),
    "recompare": dict(
        file="recompare.html", results="results_recompare.json", designs="designs.json",
        title="Minimal-Mode Tool Shootout", h1="Minimal-mode tool shootout",
        lede="The top-level comparison again, but each external tool now runs with the most "
             "simplifying option it offers itself, found in its source or docs, tested on both "
             "designs and checked by an independent reviewer. Tools with no such option keep the "
             "drawing from the first comparison. Each card shows the default beside the minimal "
             "drawing; click either for full size.",
        ours="Ours: runs/x2_l1_to_paper"),
}


def build(which: str) -> None:
    pg = PAGES[which]
    meta = json.loads((HERE / "tools.json").read_text())
    designs = json.loads((HERE / pg["designs"]).read_text())["designs"]
    rows = {(r["design"], r["tool"]): r
            for r in json.loads((OUT / pg["results"]).read_text())}
    before = {}
    if which == "recompare":
        before = {(r["design"], r["tool"]): r
                  for r in json.loads((OUT / PAGES["top"]["results"]).read_text())}
    yv = subprocess.run([YOSYS, "-V"], capture_output=True, text=True).stdout.strip()

    def cell(t: dict, d: dict) -> str:
        r = rows.get((d["name"], t["id"]))
        if r is None:
            return "<td>—</td>"
        if which == "recompare" and t not in meta["ours"]:
            if r.get("unchanged"):
                c = chip("unchanged") if r.get("svg") else chip("failed", "bad")
            else:
                c = chip("simplified", "ok") if r["status"] == "ok" else chip("failed", "bad")
        else:
            c = chip("drawn", "ok") if r["status"] == "ok" else chip("failed", "bad")
        return f'<td><a href="#{t["id"]}-{d["name"]}">{c}</a></td>'

    head = "".join(f"<th>{E(d['name'])}</th>" for d in designs)
    second = "Most minimal option" if which == "recompare" else "What it draws"
    trs = []
    for t in meta["ours"] + meta["run"]:
        info = t.get("draws", "")
        if which == "recompare" and t not in meta["ours"]:
            mn = t.get("minimal", {})
            info = mn.get("option") or ("None. " + mn.get("none", "No option found."))
        ours_cls = ' class="ours-row"' if t in meta["ours"] else ""
        trs.append(f'<tr{ours_cls}><th scope="row">{E(t["name"])}</th>'
                   f'<td class="lvl">{E(info)}</td>{"".join(cell(t, d) for d in designs)}</tr>')
    for sk in meta["skipped"]:
        trs.append(f'<tr class="skip"><th scope="row">{E(sk["name"])}</th>'
                   f'<td class="lvl">{E(sk["reason"])}</td>'
                   + "".join(f"<td>{chip('skipped')}</td>" for _ in designs) + "</tr>")
    summary = (f'<div class="tablewrap"><table class="matrix"><thead><tr><th>Tool</th>'
               f'<th>{second}</th>{head}</tr></thead><tbody>{"".join(trs)}</tbody>'
               f'</table></div>')

    tabs, panels = [], []
    for i, d in enumerate(designs):
        n = d["name"]
        files = "".join(f"<li><code>{E(f)}</code></li>" for f in d["files"])
        ours_cards = "".join(card(t, rows.get((n, t["id"])), n, ours=True)
                             for t in meta["ours"])
        if which == "recompare":
            tool_cards = "".join(compare_card(t, before.get((n, t["id"])),
                                              rows.get((n, t["id"])), n) for t in meta["run"])
        else:
            tool_cards = "".join(card(t, rows.get((n, t["id"])), n, page=which)
                                 for t in meta["run"])
        grid = "grid wide" if which == "recompare" else "grid"
        tabs.append(f'<button type="button" role="tab" id="tab-{n}" aria-controls="panel-{n}" '
                    f'aria-selected="{"true" if i == 0 else "false"}">{E(n)}'
                    f'<small>top <code>{E(d["top"])}</code></small></button>')
        panels.append(
            f'<section role="tabpanel" id="panel-{n}" aria-labelledby="tab-{n}"'
            f'{"" if i == 0 else " hidden"}>'
            f'<details class="src"><summary>RTL: {len(d["files"])} files, top '
            f'<code>{E(d["top"])}</code></summary><ul>{files}</ul></details>'
            f'<h2>Ours</h2><div class="grid two">{ours_cards}</div>'
            f'<h2>Other tools</h2><div class="{grid}">{tool_cards}</div></section>')

    stamp = time.strftime("%Y-%m-%d", time.localtime((OUT / pg["results"]).stat().st_mtime))
    chips = (chip("Designs: " + ", ".join(d["name"] for d in designs)) + chip(yv)
             + chip(pg["ours"]) + chip(f"Run {stamp}"))
    nav = " · ".join(f'<a href="{PAGES[k]["file"]}">{E(PAGES[k]["title"])}</a>'
                     if k != which else f"<b>{E(PAGES[k]['title'])}</b>" for k in PAGES)
    lede = pg["lede"].format(n_run=len(meta["run"]), n_skip=len(meta["skipped"]))
    page = TEMPLATE.format(summary=summary, tabs="".join(tabs), panels="".join(panels),
                           title=E(pg["title"]), h1=E(pg["h1"]), lede=E(lede), nav=nav,
                           designs_chips=chips)
    (OUT / pg["file"]).write_text(page)
    print(OUT / pg["file"], f"{len(page) / 1e6:.1f} MB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="all", choices=[*PAGES, "all"])
    which = ap.parse_args().set
    for k in PAGES if which == "all" else [which]:
        if (OUT / PAGES[k]["results"]).exists():
            build(k)


TEMPLATE = """<title>{title}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
/* Layout: lab notebook. Summary matrix first, then one tab per design: our two drawings
   on a wide row, every other tool's drawing in an even grid, each on a white "sheet". */
:root {{
  --bg: #f3f5f6; --panel: #ffffff; --fg: #1b2328; --muted: #5a6670; --line: #d5dce0;
  --accent: #1f6f5c; --accent-soft: #e2f0eb; --ok: #23764a; --ok-soft: #e1f2e7;
  --bad: #b3261e; --bad-soft: #fbe7e5; --sheet: #ffffff;
  --display: "IBM Plex Sans Condensed", "Arial Narrow", sans-serif;
  --body: "IBM Plex Sans", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #12171a; --panel: #1a2125; --fg: #e3e8eb; --muted: #9aa7af; --line: #2c363c;
  --accent: #5fc3a6; --accent-soft: #173a31; --ok: #6fcf97; --ok-soft: #173326;
  --bad: #ff8a80; --bad-soft: #3d1c1a; --sheet: #f7f8f8; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --bg: #12171a; --panel: #1a2125; --fg: #e3e8eb; --muted: #9aa7af; --line: #2c363c;
  --accent: #5fc3a6; --accent-soft: #173a31; --ok: #6fcf97; --ok-soft: #173326;
  --bad: #ff8a80; --bad-soft: #3d1c1a; --sheet: #f7f8f8; color-scheme: dark; }}
body {{ background: var(--bg); color: var(--fg); font: 15px/1.55 var(--body);
  padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 28px 64px; }}
main {{ max-width: 1440px; margin: 0 auto; display: grid; gap: 28px; }}
h1, h2, h3 {{ font-family: var(--display); text-wrap: balance; margin: 0; }}
h1 {{ font-size: clamp(28px, 4vw, 40px); font-weight: 600; letter-spacing: -0.01em; }}
h2 {{ font-size: 21px; font-weight: 600; margin-block: 8px 12px; }}
h3 {{ font-size: 17px; font-weight: 600; }}
code, pre {{ font-family: var(--mono); font-size: 12.5px; }}
.lede {{ max-width: 72ch; color: var(--muted); margin: 8px 0 0; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
.chip {{ display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px;
  border-radius: 999px; border: 1px solid var(--line); font-size: 12px; color: var(--muted);
  white-space: nowrap; }}
.chip.ok {{ background: var(--ok-soft); color: var(--ok); border-color: transparent; }}
.chip.bad {{ background: var(--bad-soft); color: var(--bad); border-color: transparent; }}
.chip.num {{ font-variant-numeric: tabular-nums; font-family: var(--mono); font-size: 11.5px; }}
.tablewrap {{ overflow-x: auto; background: var(--panel); border: 1px solid var(--line);
  border-radius: 8px; }}
table.matrix {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
.matrix th, .matrix td {{ text-align: left; padding: 8px 12px;
  border-bottom: 1px solid var(--line); vertical-align: top; }}
.matrix thead th {{ font-family: var(--display); font-weight: 600; color: var(--muted);
  font-size: 12.5px; text-transform: uppercase; letter-spacing: 0.06em; }}
.matrix tbody th {{ font-weight: 500; white-space: nowrap; }}
.matrix td.lvl {{ color: var(--muted); min-width: 260px; }}
.matrix tr.ours-row th {{ color: var(--accent); }}
.matrix tr.skip th, .matrix tr.skip td {{ color: var(--muted); }}
.matrix a {{ text-decoration: none; }}
[role=tablist] {{ display: flex; flex-wrap: wrap; gap: 8px; position: sticky;
  top: env(safe-area-inset-top, 0px); z-index: 5; background: var(--bg); padding-block: 10px;
  border-bottom: 1px solid var(--line); }}
body::before {{ content: ""; position: fixed; inset: 0 0 auto;
  height: env(safe-area-inset-top, 0px); z-index: 10; background: var(--bg); }}
[role=tab] {{ font: 600 16px var(--display); color: var(--fg); background: var(--panel);
  border: 1px solid var(--line); border-radius: 8px; padding: 6px 14px; cursor: pointer;
  display: grid; text-align: left; }}
[role=tab] small {{ font: 400 12px var(--body); color: var(--muted); }}
[role=tab][aria-selected=true] {{ border-color: var(--accent);
  box-shadow: inset 0 -3px 0 var(--accent); }}
[role=tab]:focus-visible, .shot:focus-visible, summary:focus-visible, .lb button:focus-visible
  {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
details.src {{ color: var(--muted); font-size: 14px; }}
details.src ul {{ margin: 6px 0 0; padding-left: 20px; }}
.grid {{ display: grid; gap: 16px;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 400px), 1fr)); }}
.grid.two {{ grid-template-columns: repeat(auto-fit, minmax(min(100%, 520px), 1fr)); }}
.card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 14px; display: grid; gap: 10px; align-content: start; min-width: 0; }}
.card.ours {{ border-color: var(--accent);
  background: linear-gradient(var(--accent-soft), var(--panel) 70px); }}
.card header {{ display: grid; gap: 2px; }}
.level {{ margin: 0; color: var(--muted); font-size: 13.5px; }}
.shot {{ display: block; box-sizing: border-box; height: 300px; width: 100%; padding: 8px;
  background: var(--sheet); border: 1px solid var(--line); border-radius: 6px; cursor: zoom-in;
  overflow: hidden; }}
.grid.two .shot {{ height: 360px; }}
.shot img {{ display: block; width: 100%; height: 100%; object-fit: contain; }}
.grid.wide {{ grid-template-columns: repeat(auto-fill, minmax(min(100%, 560px), 1fr)); }}
.pair {{ display: grid; gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); }}
figure {{ margin: 0; display: grid; gap: 4px; min-width: 0; }}
figcaption {{ font-size: 12.5px; color: var(--muted); font-variant-numeric: tabular-nums; }}
.fail.small {{ height: 300px; }}
nav.pages {{ font-size: 13.5px; color: var(--muted); margin-bottom: 10px; }}
nav.pages a {{ color: var(--accent); }}
[hidden] {{ display: none !important; }}
.fail {{ height: 300px; overflow: auto; background: var(--bad-soft); color: var(--bad);
  border-radius: 6px; padding: 10px 12px; font-size: 14px; }}
.fail pre {{ white-space: pre-wrap; word-break: break-word; color: var(--fg); margin: 6px 0 0; }}
.status {{ display: flex; flex-wrap: wrap; gap: 6px; }}
dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; margin: 0;
  font-size: 13.5px; }}
dt {{ color: var(--muted); }} dd {{ margin: 0; min-width: 0; }}
details {{ font-size: 13.5px; }}
summary {{ cursor: pointer; color: var(--accent); font-weight: 500; }}
details code {{ display: block; white-space: pre-wrap; word-break: break-word; margin-top: 6px;
  padding: 8px 10px; background: var(--bg); border-radius: 6px; }}
.dev {{ margin: 8px 0 0; padding: 6px 10px; border-left: 3px solid var(--bad); }}
.note {{ margin: 8px 0 0; color: var(--muted); }}
.lb {{ position: fixed; inset: 0; z-index: 20; background: rgba(10, 14, 16, 0.86);
  display: grid; grid-template-rows: auto 1fr; padding: env(safe-area-inset-top, 0px)
  max(12px, env(safe-area-inset-right, 0px)) env(safe-area-inset-bottom, 0px)
  max(12px, env(safe-area-inset-left, 0px)); }}
.lb .bar {{ display: flex; gap: 8px; align-items: center; padding-block: 10px; color: #e3e8eb; }}
.lb .bar span {{ flex: 1; font-family: var(--display); font-size: 17px; }}
.lb button {{ font: 500 14px var(--body); background: #26313a; color: #e3e8eb;
  border: 1px solid #3a4852; border-radius: 6px; padding: 5px 12px; cursor: pointer; }}
.lb .view {{ overflow: auto; background: #fff; border-radius: 6px; }}
.lb .view img {{ max-width: none; transform-origin: 0 0; display: block; }}
@media (prefers-reduced-motion: no-preference) {{ .shot {{ transition: border-color .15s; }} }}
.shot:hover {{ border-color: var(--accent); }}
</style>
<main>
  <header>
    <nav class="pages">{nav}</nav>
    <h1>{h1}</h1>
    <p class="lede">{lede}</p>
    <div class="meta">{designs_chips}</div>
  </header>
  <section><h2>Summary</h2>{summary}</section>
  <div role="tablist" aria-label="Design">{tabs}</div>
  {panels}
</main>
<div class="lb" id="lb" hidden role="dialog" aria-modal="true" aria-label="Full-size drawing">
  <div class="bar"><span id="lb-title"></span>
    <button type="button" id="lb-out">−</button><button type="button" id="lb-fit">Fit</button>
    <button type="button" id="lb-in">+</button>
    <button type="button" id="lb-close">Close</button></div>
  <div class="view" id="lb-view"><img id="lb-img" alt=""></div>
</div>
<script>
const tabs = [...document.querySelectorAll('[role=tab]')];
function show(name) {{
  tabs.forEach(t => {{
    const on = t.id === 'tab-' + name;
    t.setAttribute('aria-selected', on);
    document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
  }});
  try {{ localStorage.setItem('x3-tab', name); }} catch (e) {{}}
}}
tabs.forEach(t => t.addEventListener('click', () => show(t.id.slice(4))));
document.querySelectorAll('.matrix a').forEach(a => a.addEventListener('click', () => {{
  const id = a.getAttribute('href').slice(1);
  const t = tabs.find(t => id.endsWith('-' + t.id.slice(4)));
  if (t) show(t.id.slice(4));
}}));
let start = location.hash.slice(1);
if (!tabs.some(t => t.id === 'tab-' + start)) {{
  try {{ start = localStorage.getItem('x3-tab') || ''; }} catch (e) {{ start = ''; }}
}}
if (tabs.some(t => t.id === 'tab-' + start)) show(start);

const lb = document.getElementById('lb'), lbImg = document.getElementById('lb-img');
const view = document.getElementById('lb-view');
let scale = 1;
function setScale(s) {{ scale = Math.max(0.05, Math.min(8, s));
  lbImg.style.width = (lbImg.naturalWidth * scale) + 'px'; }}
function fit() {{ setScale(Math.min(view.clientWidth / lbImg.naturalWidth,
  view.clientHeight / lbImg.naturalHeight, 1)); }}
document.querySelectorAll('.shot').forEach(b => b.addEventListener('click', () => {{
  const img = b.querySelector('img');
  lbImg.src = img.src; lbImg.alt = img.alt;
  document.getElementById('lb-title').textContent = img.alt;
  lb.hidden = false;
  if (lbImg.complete) fit(); else lbImg.onload = fit;
  document.getElementById('lb-close').focus();
}}));
document.getElementById('lb-in').onclick = () => setScale(scale * 1.25);
document.getElementById('lb-out').onclick = () => setScale(scale / 1.25);
document.getElementById('lb-fit').onclick = fit;
document.getElementById('lb-close').onclick = () => {{ lb.hidden = true; }};
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') lb.hidden = true; }});
</script>
"""

if __name__ == "__main__":
    main()
