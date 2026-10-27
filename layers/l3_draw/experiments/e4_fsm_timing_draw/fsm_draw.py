"""FsmGraph v0.1 (as a dict) -> Graphviz DOT, SVG with data-rtl2d tags, Mermaid side file.

    uv run --package rtl2d-l3 python layers/l3_draw/experiments/e4_fsm_timing_draw/fsm_draw.py \
        FSM.json OUT_STEM [--engine dot]

Writes OUT_STEM.dot, OUT_STEM.svg, OUT_STEM.mmd (OUT_STEM may contain dots, e.g.
`.../uart_tx.state_q`; suffixes are appended, never substituted).

Drawing rules (plan §2 Stage 3):
- rankdir=LR, the reset state first with an entry arrow from a point node, reset drawn with a
  double border; states labelled NAME plus a small encoded value line when the value is known;
  unnamed states (S_<v> fallback) in italics; unreached states dashed grey;
- transitions labelled with their guard, wrapped and truncated at GUARD_CAP characters (the full
  guard goes into the edge's SVG <title>); guard_kind "unknown" dashed with label "?";
  guard "1" / guard_kind "always" unlabelled; self-loops drawn;
- edges whose seen_by lacks syntactic evidence ("syntactic" or "both") are purple; a legend
  lists only the styles that occur; the footer names module.state_reg, the encoding and the
  check summary (semantic / yosys / completeness) when present;
- Graphviz ids "state:<id>" / "tr:<id>"; the SVG <g> elements then get
  data-rtl2d-kind="state|transition" and data-rtl2d-id (+ data-rtl2d-src/dst on transitions),
  the e3 convention that fsm_roundtrip.check reads back.
Reads only dict keys of FsmGraph v0.1; never imports pipeline or L1 code.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from collections import deque
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARD_CAP = 40  # characters of guard text drawn on an edge (full text in <title>)
WRAP = 22  # characters per guard line
ENGINES = ("dot", "neato", "fdp", "circo")
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
C_EDGE, C_NONSYN, C_UNKNOWN, C_GREY = "#2b2b2b", "#8e44ad", "#c0392b", "#9a9a9a"
C_RESET_FILL, C_FILL = "#e8f0fb", "#ffffff"


def _sibling(name: str):
    """Load a module of this experiment by file path (works under x4_tools.load too)."""
    key = f"e4_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def _path(stem: Path, ext: str) -> Path:
    return Path(f"{stem}{ext}")


# --------------------------------------------------------------------------- labels


def fmt_value(value: int | None, width: int | None, encoding: str) -> str:
    """Encoded value line: binary for narrow / one-hot registers, hex otherwise."""
    if value is None:
        return ""
    if not width or width <= 0:
        return f"'d{value}"
    if width <= 12 or (encoding == "onehot" and width <= 16):
        return f"{width}'b{value:0{width}b}"
    return f"{width}'h{value:0{(width + 3) // 4}x}"


def guard_label(guard: str, kind: str) -> tuple[str, bool]:
    """Drawn guard text (lines joined by \\n) and whether it was truncated."""
    if kind == "unknown":
        return "?", False
    g = " ".join(guard.split())
    if kind == "always" or g in ("1", "1'b1", ""):
        return "", False
    cut = len(g) > GUARD_CAP
    if cut:
        g = g[: GUARD_CAP - 1].rstrip() + "\u2026"
    lines = textwrap.wrap(g, WRAP, break_long_words=True, break_on_hyphens=False) or [g]
    return "\n".join(lines), cut


def _dq(s: str) -> str:
    """DOT double-quoted string body (newlines become centred line breaks)."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _h(s: str) -> str:
    """Text for a Graphviz HTML label: XML-escaped, backslashes doubled. Graphviz (2.43 here)
    expands escString sequences such as \\N (node name) inside HTML labels, after decoding
    entities, so &#92; does not help; a doubled backslash renders as one."""
    return escape(str(s)).replace("\\", "\\\\")


def _syntactic(t: dict) -> bool | None:
    seen = t.get("seen_by") or []
    if not seen:
        return None
    return bool({"syntactic", "both"} & set(seen))


# --------------------------------------------------------------------------- DOT


def state_order(g: dict) -> list[dict]:
    """Reset state first, then BFS from it in transition order, then the rest in input order."""
    states = g["states"]
    by_id = {s["id"]: s for s in states}
    succ: dict[str, list[str]] = {s["id"]: [] for s in states}
    for t in g["transitions"]:
        if t["src"] in succ and t["dst"] in by_id:
            succ[t["src"]].append(t["dst"])
    roots = [s["id"] for s in states if s.get("reset")] or ([states[0]["id"]] if states else [])
    seen, order = set(roots), list(roots)
    q = deque(roots)
    while q:
        for v in succ[q.popleft()]:
            if v not in seen:
                seen.add(v)
                order.append(v)
                q.append(v)
    order += [s["id"] for s in states if s["id"] not in seen]
    return [by_id[i] for i in order]


def _state_shape(g: dict) -> str:
    longest = max((len(s["name"]) for s in g["states"]), default=0)
    return "circle" if longest <= 8 else "ellipse"


def _node_line(g: dict, s: dict, shape: str) -> str:
    val = fmt_value(s.get("value"), g.get("width"), g.get("encoding", "other"))
    name = _h(s["name"])
    if s.get("unnamed"):
        name = f"<I>{name}</I>"
    lab = name if not val else (  # two rows: a gap between the name's descenders and the value
        '<TABLE BORDER="0" CELLSPACING="0" CELLPADDING="0"><TR><TD>'
        f'{name}</TD></TR><TR><TD HEIGHT="3"></TD></TR><TR><TD>'
        f'<FONT POINT-SIZE="8" COLOR="#555555">{_h(val)}</FONT></TD></TR></TABLE>')
    attrs = [f'id="state:{_dq(s["id"])}"', f"label=<{lab}>", f"shape={shape}"]
    if s.get("reset"):
        attrs += ["peripheries=2", f'fillcolor="{C_RESET_FILL}"']
    if not s.get("reached", True):
        attrs += ['style="dashed,filled"', f'color="{C_GREY}"', f'fontcolor="{C_GREY}"']
    return f'  "{_dq(s["id"])}" [{", ".join(attrs)}];'


def _edge_line(t: dict, cut_log: list[dict]) -> str:
    lab, cut = guard_label(t.get("guard", ""), t.get("guard_kind", "expr"))
    if cut:
        cut_log.append({"what": f"guard of {t['id']} truncated to {GUARD_CAP} chars on the edge",
                        "reason": "edge label length cap (full guard kept in the SVG <title>)",
                        "lines": list(t.get("lines") or [])})
    attrs = [f'id="tr:{_dq(t["id"])}"']
    if lab:
        attrs.append(f'label="{_dq(lab)}"')
    syn = _syntactic(t)
    color = C_NONSYN if syn is False else C_EDGE
    attrs += [f'color="{color}"']
    if t.get("guard_kind") == "unknown":
        attrs += ["style=dashed", f'fontcolor="{C_UNKNOWN}"', "fontsize=11"]
    elif syn is False:
        attrs.append(f'fontcolor="{C_NONSYN}"')
    return f'  "{_dq(t["src"])}" -> "{_dq(t["dst"])}" [{", ".join(attrs)}];'


def _checks_summary(g: dict) -> str:
    ch = g.get("checks") or {}
    parts = []
    sem = (ch.get("semantic") or {}).get("semantic_check")
    if sem:
        parts.append(f"semantic: {sem}")
    yo = (ch.get("yosys") or {}).get("status")
    if yo:
        parts.append(f"yosys: {yo}")
    co = (ch.get("completeness") or {}).get("status")
    if co:
        parts.append(f"completeness: {co}")
    return " \u00b7 ".join(parts)


def _legend_items(g: dict) -> list[str]:
    ts, ss = g["transitions"], g["states"]
    items = []
    if any(_syntactic(t) is False for t in ts):
        items.append(f'<FONT COLOR="{C_NONSYN}">purple edge: not seen in the RTL text '
                     "(semantic / yosys / proof only)</FONT>")
    if any(t.get("guard_kind") == "unknown" for t in ts):
        items.append(f'<FONT COLOR="{C_UNKNOWN}">dashed edge "?": guard unknown</FONT>')
    if any(not s.get("reached", True) for s in ss):
        items.append(f'<FONT COLOR="{C_GREY}">dashed grey state: not reached from reset</FONT>')
    if any(s.get("unnamed") for s in ss):
        items.append("<I>italic state: no RTL name (S_&lt;value&gt;)</I>")
    if any(_syntactic(t) is None for t in ts):
        items.append("edge provenance (seen_by) unknown for some edges")
    return items


def _footer(g: dict) -> str:
    head = f"<B>{_h(g.get('module', '?'))}.{_h(g.get('state_reg', '?'))}</B>"
    enc = g.get("encoding", "other")
    w = g.get("width")
    meta = f"{enc}{f', {w} bit' if w else ''} \u00b7 {len(g['states'])} states \u00b7 " \
           f"{len(g['transitions'])} transitions"
    rows = [head, _h(meta)]  # one font per row: Graphviz places mixed runs by estimate
    chk = _checks_summary(g)
    if chk:
        rows.append(_h(chk))
    if g.get("status") == "rejected":
        rows.append(f'<FONT COLOR="{C_UNKNOWN}">REJECTED: '
                    f"{_h(g.get('rejected_reason') or '?')}</FONT>")
    rows += _legend_items(g)
    body = "".join(f'<TR><TD ALIGN="LEFT">{r}</TD></TR>' for r in rows)
    return f'<<TABLE BORDER="0" CELLSPACING="0" CELLPADDING="1">{body}</TABLE>>'


def to_dot(g: dict) -> tuple[str, list[dict]]:
    """DOT text and the list of drawing simplifications (truncated guards)."""
    shape = _state_shape(g)
    cut_log: list[dict] = []
    out = [
        f'digraph "{_dq(g.get("module", "fsm"))}.{_dq(g.get("state_reg", "state"))}" {{',
        '  graph [rankdir=LR, nodesep=0.45, ranksep=0.7, fontname="Helvetica", fontsize=10,'
        ' labelloc=b, labeljust=l, pad=0.2, outputorder=edgesfirst];',
        f'  node [fontname="Helvetica", fontsize=12, style=filled, fillcolor="{C_FILL}",'
        f' color="{C_EDGE}", penwidth=1.2, margin=0.04];',
        f'  edge [fontname="Helvetica", fontsize=9, color="{C_EDGE}", arrowsize=0.7];',
        f"  label={_footer(g)};",
        '  "__init" [id="init", shape=point, width=0.08, style=filled, fillcolor="#2b2b2b"];',
    ]
    order = state_order(g)
    out += [_node_line(g, s, shape) for s in order]
    reset = next((s for s in order if s.get("reset")), None)
    if reset is not None:
        out.append(f'  "__init" -> "{_dq(reset["id"])}" [id="entry", arrowsize=0.7];')
    out += [_edge_line(t, cut_log) for t in g["transitions"]]
    out.append("}")
    return "\n".join(out) + "\n", cut_log


# --------------------------------------------------------------------------- SVG


def run_graphviz(dot_text: str, engine: str = "dot", timeout: float = 60.0) -> str:
    exe = shutil.which(engine)
    if engine not in ENGINES or exe is None:
        raise RuntimeError(f"Graphviz engine {engine!r} not available (have {ENGINES})")
    r = subprocess.run([exe, "-Tsvg"], input=dot_text, capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{engine} failed: {r.stderr.strip()[:500]}")
    return r.stdout


def tag_svg(svg_text: str, g: dict) -> str:
    """Add data-rtl2d-* attributes to the Graphviz <g> elements and put the full guard in the
    edge <title>."""
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    root = ET.fromstring(svg_text)
    trs = {t["id"]: t for t in g["transitions"]}
    sids = {s["id"]: s for s in g["states"]}
    for el in root.iter(f"{{{SVG_NS}}}g"):
        gid = el.get("id") or ""
        if gid.startswith("state:") and gid[6:] in sids:
            el.set("data-rtl2d-kind", "state")
            el.set("data-rtl2d-id", gid[6:])
            el.set("data-rtl2d-name", sids[gid[6:]]["name"])
        elif gid.startswith("tr:") and gid[3:] in trs:
            t = trs[gid[3:]]
            el.set("data-rtl2d-kind", "transition")
            el.set("data-rtl2d-id", t["id"])
            el.set("data-rtl2d-src", t["src"])
            el.set("data-rtl2d-dst", t["dst"])
            title = el.find(f"{{{SVG_NS}}}title")
            if title is not None:
                title.text = (f"{t['id']}: {sids.get(t['src'], {}).get('name', t['src'])} -> "
                              f"{sids.get(t['dst'], {}).get('name', t['dst'])} "
                              f"when {t.get('guard', '')} [{t.get('guard_kind', '')}]"
                              f" seen_by={','.join(t.get('seen_by') or []) or '?'}")
        elif gid == "entry":
            el.set("data-rtl2d-kind", "entry")
            el.set("data-rtl2d-id", "entry")
        elif gid == "init":
            el.set("data-rtl2d-kind", "entry_point")
            el.set("data-rtl2d-id", "init")
    _tag_footer(root)
    return ET.tostring(root, encoding="unicode")


def _tag_footer(root: ET.Element) -> None:
    """Move the graph label texts (footer + legend) into one tagged <g>, in place."""
    graph = next((el for el in root.iter(f"{{{SVG_NS}}}g") if el.get("class") == "graph"), None)
    if graph is None:
        return
    texts = [el for el in graph if el.tag == f"{{{SVG_NS}}}text"]
    if not texts:
        return
    holder = ET.Element(f"{{{SVG_NS}}}g", {"id": "footer", "data-rtl2d-kind": "legend",
                                           "data-rtl2d-id": "footer"})
    graph.insert(list(graph).index(texts[0]), holder)
    for t in texts:
        graph.remove(t)
        holder.append(t)


# --------------------------------------------------------------------------- Mermaid


def _mid(name: str, used: dict[str, str], sid: str) -> str:
    base = "".join(c if c.isalnum() or c == "_" else "_" for c in name) or "S"
    if base[0].isdigit():
        base = "S_" + base
    cand, n = base, 1
    while cand in used.values() and used.get(sid) != cand:
        n += 1
        cand = f"{base}_{n}"
    used[sid] = cand
    return cand


def to_mermaid(g: dict) -> str:
    used: dict[str, str] = {}
    out = ["stateDiagram-v2", "  direction LR"]
    for s in state_order(g):
        mid = _mid(s["name"], used, s["id"])
        val = fmt_value(s.get("value"), g.get("width"), g.get("encoding", "other"))
        label = f"{s['name']} {val}".strip().replace('"', "'")
        out.append(f'  state "{label}" as {mid}')
        if s.get("reset"):
            out.append(f"  [*] --> {mid}")
    for t in g["transitions"]:
        lab, _ = guard_label(t.get("guard", ""), t.get("guard_kind", "expr"))
        lab = lab.replace("\n", " ").replace(";", ",").replace("#", "")
        a, b = used.get(t["src"], t["src"]), used.get(t["dst"], t["dst"])
        out.append(f"  {a} --> {b}" + (f" : {lab}" if lab else ""))
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- API


def draw(g: dict, out_stem: Path, *, engine: str = "dot") -> dict:
    """Write out_stem.{dot,svg,mmd}; return their paths, the measures and the drawing
    simplifications."""
    out_stem = Path(out_stem)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    dot_text, cuts = to_dot(g)
    svg = tag_svg(run_graphviz(dot_text, engine), g)
    p_dot, p_svg, p_mmd = (_path(out_stem, e) for e in (".dot", ".svg", ".mmd"))
    p_dot.write_text(dot_text, encoding="utf-8")
    p_svg.write_text(svg, encoding="utf-8")
    p_mmd.write_text(to_mermaid(g), encoding="utf-8")
    meas = _sibling("fsm_measure").measure(svg)
    return {"svg": str(p_svg), "dot": str(p_dot), "mmd": str(p_mmd), "measure": meas,
            "engine": engine, "simplifications": cuts}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fsm_json")
    ap.add_argument("out_stem")
    ap.add_argument("--engine", default="dot", choices=ENGINES)
    a = ap.parse_args(argv)
    g = json.loads(Path(a.fsm_json).read_text(encoding="utf-8"))
    r = draw(g, Path(a.out_stem), engine=a.engine)
    print(json.dumps(r, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
