"""x4 gallery: one self-contained HTML page per run, with a Block / FSM / Timing tab per design,
every drawing embedded, a gate table under each figure (FSM G1-G6, timing T1-T5), the
simplifications each diagram records, and the side files (FsmGraph / TimingDiagram JSON,
Mermaid, WaveDrom JSON) linked and shown in collapsible blocks with a copy button.

    uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/gallery.py \\
        --results runs/x4_fsm_timing/results.json [--out runs/x4_fsm_timing/gallery.html] \\
        [--title "x4: FSM graphs and timing diagrams"]

`build(results, out_html, title=...)` is what x4_run.py calls. The look follows x3's gallery
(pipeline/experiments/x3_tool_compare/gallery.py: tokens, chips, cards, tabs, lightbox, 1.5 MB
PNG fallback) and e3's pages.py (drawings embedded so the file works anywhere).

Each drawing is embedded as an <img> data URI rather than as <svg> markup: Graphviz, WaveDrom
and e3 SVGs reuse ids (graph0, arrow markers, clip paths), which would collide between
drawings on one page. SVGs over 1.5 MB are replaced by a PNG preview (rsvg-convert, written
to <out dir>/preview/) and the caption says so; the link to the full SVG stays.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
E = html.escape
BIG = 1.5e6  # bytes; larger SVGs are embedded as a PNG preview (as x3 does)
SIDE_MAX = 256_000  # characters of a side file shown inline; the link always has all of it

FSM_GATES = [
    ("G1", "yosys", "Yosys fsm_extract agrees after state-code mapping"),
    ("G2", "structural", "Structure: destinations exist, reset present, no unknown state"),
    ("G3", "semantic", "Semantic cross-check (consistent / subset / semantic-only)"),
    ("G4", "roundtrip", "Every state and transition appears once in the SVG"),
    ("G5", "isomorphic", "Same graph across coding-style rewrites"),
    ("G6", "completeness", "Completeness proof (SymbiYosys)"),
]
TIMING_GATES = [
    ("T1", "replay", "Every drawn value equals the VCD sample"),
    ("T2", "arrows", "Every arrow has a dependency path matching its cycle offset"),
    ("T3", "accounting", "Shown cycles + gap counts = window total, per domain"),
    ("T4", "determinism", "Two runs give the same VCD; no simulator warning"),
    ("T5", "roundtrip", "WaveDrom renders; lanes, arrows and gaps parse back"),
]
_BAD = ("fail", "disagree", "error", "mismatch", "unsupported", "timeout", "rejected")
_WARN = ("bounded", "skip", "yosys_declined", "yosys_unparsed", "declined", "unparsed",
         "n/a", "not ", "unknown", "partial", "none")
_OK = ("agree", "proven", "ok", "pass", "passed", "consistent", "consistent-subset",
       "semantic-only", "true")


# ------------------------------------------------------------------ paths and images
def resolve(p: str | Path | None) -> Path | None:
    """Absolute path of a results path (absolute, or relative to the repo root)."""
    if not p:
        return None
    q = Path(p)
    return q if q.is_absolute() else ROOT / q


def href(p: Path, base: Path) -> str:
    """Link from the page's folder to `p` (relative, so the run folder can be served)."""
    return quote(os.path.relpath(p, base).replace(os.sep, "/"))


def _preview(svg: Path, preview_dir: Path) -> Path | None:
    tag = hashlib.sha1(str(svg).encode()).hexdigest()[:10]
    png = preview_dir / f"{svg.stem}.{tag}.png"
    if png.exists() and png.stat().st_mtime >= svg.stat().st_mtime:
        return png
    exe = shutil.which("rsvg-convert")
    if not exe:
        return None
    preview_dir.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run([exe, "-w", "3000", "-b", "white", str(svg), "-o", str(png)],
                           capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return None
    return png if r.returncode == 0 and png.exists() else None


def image(svg: Path, preview_dir: Path) -> tuple[str | None, str]:
    """(data URI or None, size note) for one drawing."""
    n = svg.stat().st_size
    kb = n / 1024
    size = f"{kb:,.0f} KB" if kb < 1024 else f"{kb / 1024:,.1f} MB"
    if n <= BIG:
        return "data:image/svg+xml;base64," + base64.b64encode(svg.read_bytes()).decode(), size
    png = _preview(svg, preview_dir)
    if png is None:
        return None, f"{size} SVG, too large to embed and no PNG preview could be made"
    uri = "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode()
    return uri, f"{size} SVG, shown as PNG"


# ------------------------------------------------------------------ small pieces
def chip(text: str, cls: str = "") -> str:
    return f'<span class="chip {cls}">{E(text)}</span>'


def gate_state(d) -> tuple[str, str]:
    """(ok | bad | warn, status text) of one gate dict as fsm_spec.Checks / timing checks
    store it: {status: ...} or {ok: bool, ...}; empty = not run."""
    if not d:
        return "warn", "not run"
    if not isinstance(d, dict):
        return ("ok", "ok") if d is True else ("bad", str(d))
    st = d.get("status", d.get("semantic_check"))
    if st is not None:
        s = str(st).lower()
        text = str(st) + (" (forced)" if d.get("forced") else "")
        if s.startswith(_BAD):
            return "bad", text
        if s.startswith(_WARN):
            return "warn", text
        if s in _OK or s.startswith("proven"):
            return ("bad", text) if d.get("ok") is False else ("ok", text)
        if "ok" in d:
            return ("ok" if d["ok"] else "bad"), text
        return "warn", text
    if d.get("skipped"):
        return "warn", f"skipped: {d['skipped']}" if isinstance(d["skipped"], str) else "skipped"
    if "ok" in d:
        if d["ok"] is None:
            return "warn", "n/a"
        return ("ok", "ok") if d["ok"] else ("bad", "fail")
    return "warn", "no verdict"


def _short(v, n: int = 90) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str, ensure_ascii=False)
    return s if len(s) <= n else s[: n - 1] + "…"


def gate_detail(d) -> str:
    """Compact text of everything in a gate dict besides its verdict."""
    if not isinstance(d, dict):
        return ""
    parts = []
    for k, v in d.items():
        if k in ("status", "ok", "forced") or v in (None, "", [], {}):
            continue
        if isinstance(v, list):
            parts.append(f"{k}: {len(v)}" + (f" (first: {_short(v[0], 70)})" if v else ""))
        else:
            parts.append(f"{k}: {_short(v)}")
    s = " · ".join(parts)
    return s if len(s) <= 420 else s[:419] + "…"


def gate_table(checks: dict, gates: list[tuple[str, str, str]]) -> str:
    rows = []
    for gid, key, what in gates:
        d = (checks or {}).get(key)
        cls, text = gate_state(d)
        rows.append(f'<tr><th scope="row"><b>{gid}</b> {E(what)}</th>'
                    f'<td class="g {cls}">{E(text)}</td>'
                    f'<td class="det">{E(gate_detail(d))}</td></tr>')
    return ('<div class="tablewrap"><table class="gates"><thead><tr><th>Gate</th>'
            '<th>Status</th><th>Detail</th></tr></thead><tbody>' + "".join(rows)
            + "</tbody></table></div>")


def gate_strip(checks: dict, gates: list[tuple[str, str, str]]) -> str:
    cells, tips = [], []
    for gid, key, _ in gates:
        cls, text = gate_state((checks or {}).get(key))
        cells.append(f'<i class="{cls}">{gid}</i>')
        tips.append(f"{gid} {text}")
    return f'<span class="strip" title="{E("; ".join(tips))}">{"".join(cells)}</span>'


def _line(x) -> str:
    if isinstance(x, dict):
        f = x.get("file")
        return f"{Path(f).name if f else '?'}:{x.get('line', '?')}"
    return str(x)


def simplifications(items: list[dict]) -> str:
    if not items:
        return '<p class="note">No simplification recorded.</p>'
    rows = "".join(
        f"<tr><td>{E(str(s.get('what', '')))}</td><td>{E(str(s.get('reason', '')))}</td>"
        f"<td><code>{E(', '.join(_line(x) for x in s.get('lines') or []) or '—')}</code></td>"
        f"</tr>" for s in items)
    return ('<div class="tablewrap"><table class="simpl"><thead><tr><th>What</th><th>Reason'
            '</th><th>Lines</th></tr></thead><tbody>' + rows + "</tbody></table></div>")


def side_file(label: str, p: Path | None, base: Path, *, show: bool) -> str:
    """A link to a side file; with show=True its text in a <details> with a copy button."""
    if p is None:
        return ""
    if not p.exists():
        return f'<li>{E(label)}: <span class="note">missing ({E(p.name)})</span></li>'
    link = f'<a href="{href(p, base)}">{E(p.name)}</a>'
    if not show:
        return f"<li>{E(label)}: {link}</li>"
    text = p.read_text(encoding="utf-8", errors="replace")
    cut = ""
    if len(text) > SIDE_MAX:
        text, cut = text[:SIDE_MAX], f" (first {SIDE_MAX:,} characters; the link has all)"
    return (f'<li><details class="side"><summary>{E(label)}{E(cut)}</summary>'
            f'<div class="sidebar">{link}<button type="button" class="copy">Copy</button>'
            f'</div><pre>{E(text)}</pre></details></li>')


def figure(svg: Path | None, alt: str, caption: str, preview_dir: Path) -> str:
    if svg is None or not svg.exists():
        what = "no drawing" if svg is None else f"drawing missing: {svg.name}"
        return f'<div class="fail small"><b>{E(what)}</b></div>'
    src, size = image(svg, preview_dir)
    if src is None:
        return f'<div class="fail small"><b>{E(size)}</b></div>'
    return (f'<figure><button class="shot" type="button" aria-label="Open {E(alt)} full size">'
            f'<img src="{src}" alt="{E(alt)}" decoding="async"></button>'
            f'<figcaption>{caption} · {E(size)}</figcaption></figure>')


# ------------------------------------------------------------------ cards
def block_card(r: dict, base: Path, pdir: Path) -> str:
    b = r.get("block")
    if b is None:
        return '<p class="empty">The block diagram was not requested for this run.</p>'
    svg = resolve(b.get("svg"))
    head = (f'<header><h3>Block diagram of <code>{E(r.get("top") or "")}</code></h3>'
            '<p class="level">x1 bridge (L2 stand-in) → x2 adapter → e3 paper engine; '
            'L1 heuristic labels</p></header>')
    if not b.get("ok") or not _exists(svg):
        err = b.get("error") or ("no drawing" if svg is None else
                                 f"the stage reported ok but {svg.name} is missing")
        return (f'<article class="card">{head}<div class="fail"><b>Block diagram failed</b>'
                f'<pre>{E(str(err))}</pre></div></article>')
    cap = f"Block diagram of {E(r['design'])}: units, their connections and the top's ports"
    notes = "".join(f"<li>{E(str(n))}</li>" for n in b.get("notes") or [])
    more = (f'<details><summary>Notes and simplifications ({len(b.get("notes") or [])})'
            f'</summary><ul class="notes">{notes}</ul></details>' if notes else "")
    links = f'<ul class="files">{side_file("SVG", svg, base, show=False)}</ul>'
    fig = figure(svg, f"block diagram of {r['design']}", cap, pdir)
    return (f'<article class="card">{head}{fig}'
            f'<div class="status">{chip("drawn", "ok")}</div>{more}{links}</article>')


def _fsm_caption(f: dict) -> str:
    bits = [f"FSM <code>{E(f['id'])}</code>"]
    if f.get("states") is not None:
        bits.append(f"{f['states']} states, {f.get('transitions', '?')} transitions")
    if f.get("encoding"):
        bits.append(f"{E(str(f['encoding']))} encoding")
    if f.get("engine"):
        bits.append(f"engine {E(str(f['engine']))}")
    return " · ".join(bits)


def _exists(p: Path | None) -> bool:
    return p is not None and p.is_file()


def _drawn(row: dict) -> bool:
    """A figure counts as drawn only when its status is ok and its SVG file is there."""
    return row.get("status", "ok") == "ok" and _exists(resolve(row.get("svg")))


def _drawn_chip(row: dict) -> str:
    if row.get("status", "ok") != "ok":
        return chip("rejected", "bad")
    return chip("drawn", "ok") if _drawn(row) else chip("not drawn", "bad")


def fsm_card(f: dict, base: Path, pdir: Path, cid: str) -> str:
    svg, js, mmd = resolve(f.get("svg")), resolve(f.get("json")), resolve(f.get("mmd"))
    cap = _fsm_caption(f)
    ok = f.get("status", "ok") == "ok"
    head = (f'<header><h3><code>{E(f["id"])}</code></h3><p class="level">State graph: L1 '
            f'hybrid FSM → x4 fsm_bridge (FsmGraph v0.1) → e4 fsm_draw</p></header>')
    body = (figure(svg, f"FSM {f['id']}", cap, pdir) if ok else
            f'<div class="fail small"><b>Rejected</b><pre>{E(str(f.get("rejected_reason")))}'
            f'</pre></div>')
    status = _drawn_chip(f)
    sims = f.get("simplifications") or []
    files = "".join([side_file("FsmGraph JSON", js, base, show=False),
                     side_file("SVG", svg, base, show=False) if ok else "",
                     side_file("Mermaid text (.mmd)", mmd, base, show=True)])
    return (f'<article class="card" id="{E(cid)}">{head}{body}'
            f'<div class="status">{status}{gate_strip(f.get("checks"), FSM_GATES)}</div>'
            f'{gate_table(f.get("checks") or {}, FSM_GATES)}'
            f'<details{" open" if 0 < len(sims) <= 4 else ""}><summary>Simplifications '
            f'({len(sims)})</summary>{simplifications(sims)}</details>'
            f'<ul class="files">{files}</ul></article>')


def _timing_caption(t: dict) -> str:
    bits = [f"Interface <code>{E(str(t.get('interface')))}</code>"
            + (f" ({E(str(t['protocol']))})" if t.get("protocol") else ""),
            f"scenario {E(str(t.get('scenario')))}"]
    if t.get("lanes") is not None:
        bits.append(f"{t['lanes']} lanes in {t.get('domains', '?')} clock domain(s), "
                    f"{t.get('arrows', '?')} arrows, {t.get('gaps', '?')} gaps")
    return " · ".join(bits)


def timing_card(t: dict, base: Path, pdir: Path, cid: str) -> str:
    svg, js, wd = resolve(t.get("svg")), resolve(t.get("json")), resolve(t.get("wavedrom"))
    cap = _timing_caption(t)
    head = (f'<header><h3><code>{E(t["id"])}</code></h3><p class="level">Timing diagram: '
            f'simulation VCD → x4 timing_bridge (TimingDiagram v0.1) → e4 wave_draw (WaveDrom)'
            f'</p></header>')
    sims = t.get("simplifications") or []
    files = "".join([side_file("TimingDiagram JSON", js, base, show=False),
                     side_file("SVG", svg, base, show=False),
                     side_file("WaveDrom JSON", wd, base, show=True)])
    return (f'<article class="card wide" id="{E(cid)}">{head}'
            f'{figure(svg, f"timing diagram {t["id"]}", cap, pdir)}'
            f'<div class="status">{_drawn_chip(t)}'
            f'{gate_strip(t.get("checks"), TIMING_GATES)}</div>'
            f'{gate_table(t.get("checks") or {}, TIMING_GATES)}'
            f'<details{" open" if 0 < len(sims) <= 4 else ""}><summary>Simplifications '
            f'({len(sims)})</summary>{simplifications(sims)}</details>'
            f'<ul class="files">{files}</ul></article>')


# ------------------------------------------------------------------ panels
def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", s)


def _notes_for(r: dict, part: str) -> str:
    ns = [n for n in r.get("notes") or [] if str(n).lower().startswith(part)]
    return "".join(f'<p class="empty">{E(str(n))}</p>' for n in ns)


def _cid(did: str, part: str, i: int, rid: str) -> str:
    """Card id unique on the page: design index, part, row index, then the readable id."""
    return f"{did}-{part}{i}-{_slug(rid)}"


def fsm_panel(r: dict, base: Path, pdir: Path, did: str = "d0") -> str:
    rows = r.get("fsm") or []
    ok = [f for f in rows if f.get("status", "ok") == "ok"]
    rej = [f for f in rows if f.get("status", "ok") != "ok"]
    out = [_notes_for(r, "fsm")]
    if not rows:
        out.append('<p class="empty">No FSM was found in this design (or the FSM part was not '
                   'requested).</p>')
    if ok:
        cards = "".join(fsm_card(f, base, pdir, _cid(did, "fsm", i, f["id"]))
                        for i, f in enumerate(ok))
        out.append(f'<div class="grid two">{cards}</div>')
    if rej:
        items = "".join(
            f'<li><code>{E(f["id"])}</code>: {E(str(f.get("rejected_reason")))}'
            + (f' · <a href="{href(resolve(f["json"]), base)}">FsmGraph JSON</a>'
               if _exists(resolve(f.get("json"))) else "") + "</li>" for f in rej)
        out.append(f'<section class="rejected"><h3>Rejected FSMs ({len(rej)})</h3>'
                   f'<p class="note">Not drawn in the gallery: G2 or G3 failed (plan §1). '
                   f'Their drawings, if any, are under <code>fsm_rejected/</code>.</p>'
                   f'<ul>{items}</ul></section>')
    return "".join(out)


def timing_panel(r: dict, base: Path, pdir: Path, did: str = "d0") -> str:
    rows = r.get("timing") or []
    out = [_notes_for(r, "timing")]
    if not rows:
        out.append('<p class="empty">No timing diagram: no structurally confirmed interface, no '
                   'handshake event in the simulation, or the timing part was not requested.</p>')
    else:
        cards = "".join(timing_card(t, base, pdir, _cid(did, "tim", i, str(t.get("id"))))
                        for i, t in enumerate(rows))
        out.append(f'<div class="grid one">{cards}</div>')
    return "".join(out)


def _counts(r: dict) -> tuple[int, int, int, bool]:
    """(FSMs drawn, FSMs rejected, timing diagrams drawn, block drawn); drawn = file exists."""
    fsm = r.get("fsm") or []
    drawn = sum(1 for f in fsm if _drawn(f))
    rej = sum(1 for f in fsm if f.get("status", "ok") != "ok")
    ntim = sum(1 for t in r.get("timing") or [] if _drawn(t))
    b = r.get("block") or {}
    return drawn, rej, ntim, bool(b.get("ok")) and _exists(resolve(b.get("svg")))


def design_panel(k: int, r: dict, base: Path, pdir: Path, first: bool) -> str:
    did = f"d{k}"
    nfsm, nrej, ntim, bok = _counts(r)
    files = "".join(f"<li><code>{E(str(f))}</code></li>" for f in r.get("files") or [])
    errs = r.get("errors") or []
    err_box = ""
    if errs:
        items = "".join(f"<li>{E(str(e))}</li>" for e in errs)
        err_box = f'<div class="fail inline"><b>Stage errors</b><ul>{items}</ul></div>'
    nothing = ""
    if not (nfsm or ntim or bok):
        nothing = ('<div class="callout">Nothing could be drawn for this design. The reasons are '
                   'listed above and in each tab.</div>')
    other = [n for n in r.get("notes") or []
             if not str(n).lower().startswith(("fsm", "timing"))]
    notes = ("<ul class=\"notes\">" + "".join(f"<li>{E(str(n))}</li>" for n in other)
             + "</ul>") if other else ""
    parts = [("block", "Block", 1 if bok else 0, block_card(r, base, pdir)),
             ("fsm", "FSM", nfsm, fsm_panel(r, base, pdir, did)),
             ("timing", "Timing", ntim, timing_panel(r, base, pdir, did))]
    sel = next((p[0] for p in parts if p[2]), "block")
    tabs = "".join(
        f'<button type="button" role="tab" id="tab-{did}-{p}" aria-controls="panel-{did}-{p}" '
        f'aria-selected="{"true" if p == sel else "false"}">{lab} <small>{n}</small></button>'
        for p, lab, n, _ in parts)
    panels = "".join(
        f'<div role="tabpanel" id="panel-{did}-{p}" aria-labelledby="tab-{did}-{p}"'
        f'{"" if p == sel else " hidden"}>{body}</div>' for p, _, _, body in parts)
    secs = r.get("seconds")
    chips = (chip(f"top {r.get('top') or '?'}") + (chip(f"{secs} s", "num") if secs is not None
                                                     else ""))
    return (f'<section role="tabpanel" class="design" id="panel-{did}" '
            f'aria-labelledby="tab-{did}"{"" if first else " hidden"}>'
            f'<div class="dhead"><h2>{E(r["design"])}</h2><div class="meta">{chips}</div>'
            f'<details class="src"><summary>RTL: {len(r.get("files") or [])} file(s)</summary>'
            f'<ul>{files}</ul></details></div>{err_box}{notes}{nothing}'
            f'<div role="tablist" class="parts" aria-label="Diagram kind">{tabs}</div>'
            f'{panels}</section>')


def _secs(v) -> str:
    return "" if v is None else str(v)


def summary(results: list[dict]) -> str:
    trs = []
    for k, r in enumerate(results):
        nfsm, nrej, ntim, bok = _counts(r)
        b = r.get("block")
        bchip = (chip("not requested") if b is None else
                 chip("drawn", "ok") if bok else chip("failed", "bad"))
        nmiss = len(r.get("fsm") or []) - nfsm - nrej
        fchip = chip(f"{nfsm} drawn", "ok" if nfsm else "") + (
            chip(f"{nrej} rejected", "bad") if nrej else "") + (
            chip(f"{nmiss} not drawn", "bad") if nmiss else "")
        strips = "".join(gate_strip(f.get("checks"), FSM_GATES) for f in r.get("fsm") or []
                         if f.get("status", "ok") == "ok")
        tstrips = "".join(gate_strip(t.get("checks"), TIMING_GATES)
                          for t in r.get("timing") or [])
        errs = len(r.get("errors") or [])
        trs.append(
            f'<tr><th scope="row"><a href="#d{k}" data-design="d{k}">{E(r["design"])}</a>'
            f'</th><td>{bchip}</td><td>{fchip}<div>{strips}</div></td>'
            f'<td>{chip(f"{ntim} drawn", "ok" if ntim else "")}<div>{tstrips}</div></td>'
            f'<td>{chip(f"{errs} errors", "bad") if errs else chip("none")}</td>'
            f'<td class="num">{E(_secs(r.get("seconds")))}</td></tr>')
    return ('<div class="tablewrap"><table class="matrix"><thead><tr><th>Design</th>'
            '<th>Block</th><th>FSM (gates G1–G6)</th><th>Timing (gates T1–T5)</th>'
            '<th>Errors</th><th>Seconds</th></tr></thead><tbody>' + "".join(trs)
            + "</tbody></table></div>")


def build(results: list[dict], out_html: Path, *, title: str) -> Path:
    """Write the gallery page for `results` (x4_run.py result rows) and return its path."""
    out_html = Path(out_html)
    if not out_html.is_absolute():
        out_html = ROOT / out_html
    out_html.parent.mkdir(parents=True, exist_ok=True)
    base, pdir = out_html.parent, out_html.parent / "preview"
    tabs = "".join(
        f'<button type="button" role="tab" id="tab-d{k}" aria-controls="panel-d{k}" '
        f'aria-selected="{"true" if k == 0 else "false"}">{E(r["design"])}'
        f'<small>top <code>{E(str(r.get("top")))}</code></small></button>'
        for k, r in enumerate(results))
    panels = "".join(design_panel(k, r, base, pdir, k == 0) for k, r in enumerate(results))
    nf = sum(_counts(r)[0] for r in results)
    nt = sum(_counts(r)[2] for r in results)
    chips = (chip(f"{len(results)} design(s)") + chip(f"{nf} FSM graph(s)")
             + chip(f"{nt} timing diagram(s)") + chip(time.strftime("Built %Y-%m-%d %H:%M")))
    design_tabs = (f'<div role="tablist" class="designs" aria-label="Design">{tabs}</div>'
                   if len(results) > 1 else "")
    if not results:
        panels = '<div class="callout">No design in this run.</div>'
    page = "".join([
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<title>{E(title)}</title><style>{CSS}</style></head><body><main><header>",
        f"<h1>{E(title)}</h1><p class=\"lede\">{E(LEDE)}</p>",
        f"<div class=\"meta\">{chips}</div></header>",
        f"<section><h2>Summary</h2>{summary(results)}</section>" if len(results) > 1 else "",
        design_tabs, panels, "</main>", LIGHTBOX, f"<script>{JS}</script></body></html>"])
    out_html.write_text(page, encoding="utf-8")
    return out_html


LEDE = ("Each design has three tabs: the block diagram (units and their connections), one "
        "state graph per FSM, and timing diagrams per interface. Under every figure, the gate "
        "table shows each check: green passed, red failed, yellow skipped, bounded or not run. "
        "Every simplification made on the data is listed with its reason and source lines. "
        "Click a drawing to open it full size.")

CSS = """
:root { --bg:#f3f5f6; --panel:#fff; --fg:#1b2328; --muted:#5a6670; --line:#d5dce0;
  --accent:#1f6f5c; --accent-soft:#e2f0eb; --ok:#23764a; --ok-soft:#e1f2e7; --bad:#b3261e;
  --bad-soft:#fbe7e5; --warn:#7a5a00; --warn-soft:#fbf0cf; --sheet:#fff;
  --display:"IBM Plex Sans Condensed","Arial Narrow",sans-serif;
  --body:"IBM Plex Sans",system-ui,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg:#12171a; --panel:#1a2125; --fg:#e3e8eb; --muted:#9aa7af; --line:#2c363c;
  --accent:#5fc3a6; --accent-soft:#173a31; --ok:#6fcf97; --ok-soft:#173326; --bad:#ff8a80;
  --bad-soft:#3d1c1a; --warn:#f2c94c; --warn-soft:#3a3115; --sheet:#f7f8f8; color-scheme:dark; } }
:root[data-theme="dark"] { --bg:#12171a; --panel:#1a2125; --fg:#e3e8eb; --muted:#9aa7af;
  --line:#2c363c; --accent:#5fc3a6; --accent-soft:#173a31; --ok:#6fcf97; --ok-soft:#173326;
  --bad:#ff8a80; --bad-soft:#3d1c1a; --warn:#f2c94c; --warn-soft:#3a3115; --sheet:#f7f8f8;
  color-scheme:dark; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.55 var(--body);
  padding:28px max(16px, env(safe-area-inset-right, 0px)) 64px
    max(16px, env(safe-area-inset-left, 0px)); }
main { max-width:1440px; margin:0 auto; display:grid; gap:24px; min-width:0; }
h1, h2, h3 { font-family:var(--display); text-wrap:balance; margin:0; }
h1 { font-size:clamp(26px, 4vw, 38px); font-weight:600; }
h2 { font-size:21px; font-weight:600; margin-block:4px 10px; }
h3 { font-size:17px; font-weight:600; overflow-wrap:anywhere; }
code, pre { font-family:var(--mono); font-size:12.5px; }
.lede { max-width:80ch; color:var(--muted); margin:8px 0 0; }
.meta, .status { display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
.meta { margin-top:10px; }
.chip { display:inline-flex; align-items:center; padding:1px 8px; border-radius:999px;
  border:1px solid var(--line); font-size:12px; color:var(--muted); white-space:nowrap; }
.chip.ok { background:var(--ok-soft); color:var(--ok); border-color:transparent; }
.chip.bad { background:var(--bad-soft); color:var(--bad); border-color:transparent; }
.chip.num, td.num { font-variant-numeric:tabular-nums; font-family:var(--mono); font-size:12px; }
.strip { display:inline-flex; gap:2px; margin:3px 6px 0 0; }
.strip i { font:500 10.5px var(--mono); font-style:normal; padding:0 4px; border-radius:3px; }
i.ok, td.g.ok { background:var(--ok-soft); color:var(--ok); }
i.bad, td.g.bad { background:var(--bad-soft); color:var(--bad); }
i.warn, td.g.warn { background:var(--warn-soft); color:var(--warn); }
.tablewrap { overflow-x:auto; background:var(--panel); border:1px solid var(--line);
  border-radius:8px; }
table { border-collapse:collapse; width:100%; font-size:13.5px; }
th, td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line);
  vertical-align:top; }
thead th { font-family:var(--display); font-weight:600; color:var(--muted); font-size:12px;
  text-transform:uppercase; letter-spacing:.06em; }
tbody th { font-weight:500; }
table.gates tbody th { font-weight:400; min-width:180px; }
td.g { font-weight:600; white-space:nowrap; }
td.det { color:var(--muted); font-size:12.5px; overflow-wrap:anywhere; min-width:200px; }
table.simpl td { overflow-wrap:anywhere; }
[role=tablist] { display:flex; flex-wrap:wrap; gap:8px; }
.designs { position:sticky; top:0; z-index:5; background:var(--bg); padding-block:10px;
  border-bottom:1px solid var(--line); }
[role=tab] { font:600 15px var(--display); color:var(--fg); background:var(--panel);
  border:1px solid var(--line); border-radius:8px; padding:6px 14px; cursor:pointer;
  display:grid; text-align:left; }
[role=tab] small { font:400 12px var(--body); color:var(--muted); }
.parts [role=tab] { display:inline-flex; gap:8px; align-items:baseline; }
[role=tab][aria-selected=true] { border-color:var(--accent);
  box-shadow:inset 0 -3px 0 var(--accent); }
[role=tab]:focus-visible, .shot:focus-visible, summary:focus-visible, button:focus-visible
  { outline:2px solid var(--accent); outline-offset:2px; }
section.design { display:grid; gap:14px; min-width:0; }
.dhead { display:grid; gap:4px; }
details.src { color:var(--muted); font-size:14px; }
details ul { margin:6px 0 0; padding-left:20px; }
.grid { display:grid; gap:16px; }
.grid.two { grid-template-columns:repeat(auto-fit, minmax(min(100%, 520px), 1fr)); }
.grid.one { grid-template-columns:minmax(0, 1fr); }
.card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px;
  display:grid; gap:10px; align-content:start; min-width:0; }
.card header { display:grid; gap:2px; }
.level { margin:0; color:var(--muted); font-size:13.5px; }
.shot { display:block; height:380px; width:100%; padding:8px; background:var(--sheet);
  border:1px solid var(--line); border-radius:6px; cursor:zoom-in; overflow:hidden; }
.card.wide .shot { height:auto; max-height:520px; }
.card.wide .shot img { height:auto; max-height:500px; }
.shot:hover { border-color:var(--accent); }
.shot img { display:block; width:100%; height:100%; object-fit:contain; }
figure { margin:0; display:grid; gap:4px; min-width:0; }
figcaption { font-size:12.5px; color:var(--muted); }
.fail { overflow:auto; background:var(--bad-soft); color:var(--bad); border-radius:6px;
  padding:10px 12px; font-size:14px; }
.fail.small { min-height:120px; }
.fail pre { white-space:pre-wrap; word-break:break-word; color:var(--fg); margin:6px 0 0; }
.fail ul { margin:4px 0 0; color:var(--fg); }
.callout { background:var(--warn-soft); color:var(--fg); border-left:4px solid var(--warn);
  padding:10px 14px; border-radius:6px; }
.empty { color:var(--muted); margin:6px 0; }
.note { color:var(--muted); margin:4px 0; font-size:13px; }
ul.notes { margin:0; padding-left:20px; color:var(--muted); font-size:13.5px; }
ul.files { list-style:none; margin:0; padding:0; display:grid; gap:4px; font-size:13.5px; }
details { font-size:13.5px; min-width:0; }
summary { cursor:pointer; color:var(--accent); font-weight:500; }
details.side pre { max-height:320px; overflow:auto; margin:6px 0 0; padding:8px 10px;
  background:var(--bg); border-radius:6px; white-space:pre; }
.sidebar { display:flex; gap:10px; align-items:center; margin-top:6px; }
button.copy { font:500 12.5px var(--body); background:var(--panel); color:var(--fg);
  border:1px solid var(--line); border-radius:6px; padding:2px 10px; cursor:pointer; }
a { color:var(--accent); }
section.rejected ul { padding-left:20px; }
[hidden] { display:none !important; }
.lb { position:fixed; inset:0; z-index:20; background:rgba(10,14,16,.86); display:grid;
  grid-template-rows:auto 1fr; padding:0 12px 12px; }
.lb .bar { display:flex; gap:8px; align-items:center; padding-block:10px; color:#e3e8eb; }
.lb .bar span { flex:1; font-family:var(--display); font-size:17px; overflow-wrap:anywhere; }
.lb button { font:500 14px var(--body); background:#26313a; color:#e3e8eb;
  border:1px solid #3a4852; border-radius:6px; padding:5px 12px; cursor:pointer; }
.lb .view { overflow:auto; background:#fff; border-radius:6px; }
.lb .view img { max-width:none; transform-origin:0 0; display:block; }
"""

LIGHTBOX = """<div class="lb" id="lb" hidden role="dialog" aria-modal="true"
  aria-label="Full-size drawing"><div class="bar"><span id="lb-title"></span>
  <button type="button" id="lb-out">&minus;</button><button type="button" id="lb-fit">Fit</button>
  <button type="button" id="lb-in">+</button><button type="button" id="lb-close">Close</button>
  </div><div class="view" id="lb-view"><img id="lb-img" alt=""></div></div>"""

JS = """
function select(tab) {
  const list = tab.closest('[role=tablist]');
  list.querySelectorAll(':scope > [role=tab]').forEach(t => {
    const on = t === tab;
    t.setAttribute('aria-selected', on);
    const p = document.getElementById(t.getAttribute('aria-controls'));
    if (p) p.hidden = !on;
  });
  if (list.classList.contains('designs')) {
    try { localStorage.setItem('x4-design', tab.id); } catch (e) {}
  }
}
document.querySelectorAll('[role=tab]').forEach(t => t.addEventListener('click', () => select(t)));
function showDesign(id) {
  const t = document.getElementById('tab-' + id);
  if (t) { select(t); return true; }
  return false;
}
document.querySelectorAll('a[data-design]').forEach(a => a.addEventListener('click', () =>
  showDesign(a.dataset.design)));
let start = location.hash.slice(1);
if (!showDesign(start)) {
  try { const s = localStorage.getItem('x4-design');
        if (s && document.getElementById(s)) select(document.getElementById(s)); } catch (e) {}
}
document.querySelectorAll('button.copy').forEach(b => b.addEventListener('click', async () => {
  const pre = b.closest('details').querySelector('pre');
  const text = pre.textContent;
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const r = document.createRange(); r.selectNodeContents(pre);
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    try { document.execCommand('copy'); } catch (e2) {}
  }
  const old = b.textContent; b.textContent = 'Copied'; setTimeout(() => b.textContent = old, 1200);
}));
const lb = document.getElementById('lb'), lbImg = document.getElementById('lb-img');
const view = document.getElementById('lb-view');
let scale = 1;
function setScale(s) { scale = Math.max(0.05, Math.min(8, s));
  lbImg.style.width = (lbImg.naturalWidth * scale) + 'px'; }
function fit() { setScale(Math.min(view.clientWidth / lbImg.naturalWidth,
  view.clientHeight / lbImg.naturalHeight, 1)); }
document.querySelectorAll('.shot').forEach(b => b.addEventListener('click', () => {
  const img = b.querySelector('img');
  lbImg.src = img.src; lbImg.alt = img.alt;
  document.getElementById('lb-title').textContent = img.alt;
  lb.hidden = false;
  if (lbImg.complete) fit(); else lbImg.onload = fit;
  document.getElementById('lb-close').focus();
}));
document.getElementById('lb-in').onclick = () => setScale(scale * 1.25);
document.getElementById('lb-out').onclick = () => setScale(scale / 1.25);
document.getElementById('lb-fit').onclick = fit;
document.getElementById('lb-close').onclick = () => { lb.hidden = true; };
document.addEventListener('keydown', e => { if (e.key === 'Escape') lb.hidden = true; });
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, help="results.json written by x4_run.py")
    ap.add_argument("--out", help="default: gallery.html next to results.json")
    ap.add_argument("--title", default="x4: FSM graphs and timing diagrams")
    a = ap.parse_args(argv)
    res = resolve(a.results)
    out = resolve(a.out) if a.out else res.parent / "gallery.html"
    page = build(json.loads(res.read_text(encoding="utf-8")), out, title=a.title)
    print(page, f"{page.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
