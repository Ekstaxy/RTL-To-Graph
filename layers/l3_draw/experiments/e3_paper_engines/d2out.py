"""The paper-figure graph as D2 source, laid out and drawn by D2 itself (D2 0.9.0).

D2 is the one tool here with its own figure grammar (containers with titles, arrows,
`grid-columns`), so it is shown with its own renderer and routing. The same graph and
colours are used. These drawings carry no data-rtl2d attributes and are not measured by
measure3; the README says so.

  d2_dagre  D2 + dagre (layered)        d2_elk   D2 + ELK (bundled)
  d2_tala   D2 + TALA (proprietary, D2's own orthogonal engine; watermark without licence)
  d2_grid   dagre, every container a grid (`grid-columns`), the "table of units" look
"""

from __future__ import annotations

import math
import re

import p3lib
from grammar import PGraph
from paper import CAT, SUBSYS


def _key(nid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", nid)


def source(g: PGraph, grid: bool = False) -> str:
    out = ["direction: right", "classes: {",
           "  bar: {style.fill: '#d0d0d0'; style.bold: true}", "}"]

    def path(nid: str) -> str:
        return ".".join(_key(x) for x in [*g.chain(nid), nid])

    def emit(nid: str, ind: str) -> None:
        n = g.nodes[nid]
        lab = n.label.replace('"', "'")
        if n.kind == "container":
            fill, line = SUBSYS[g.colour_of.get(g.top_of(nid), 0) % len(SUBSYS)]
            out.append(f'{ind}{_key(nid)}: "{lab}" {{')
            out.append(f"{ind}  style.fill: '{fill if not n.parent else '#ffffff'}'")
            out.append(f"{ind}  style.stroke: '{line}'")
            if n.parent:
                out.append(f"{ind}  style.stroke-dash: 3")
            if n.count > 1:
                out.append(f"{ind}  style.multiple: true")
            kids = g.children.get(nid, [])
            if grid and len(kids) > 2:
                out.append(f"{ind}  grid-columns: {max(2, round(math.sqrt(len(kids) * 1.6)))}")
                out.append(f"{ind}  grid-gap: 30")
            for k in kids:
                emit(k, ind + "  ")
            out.append(f"{ind}}}")
            return
        if n.kind == "bar":
            out.append(f'{ind}{_key(nid)}: "{lab}" {{class: bar; width: {int(n.w)}; height: 26}}')
        elif n.kind == "pin":
            out.append(f'{ind}{_key(nid)}: "{lab}" {{shape: text}}')
        else:
            fill = CAT.get(n.cat, CAT["compute"])[0]
            mult = "; style.multiple: true" if n.count > 1 else ""
            out.append(f"{ind}{_key(nid)}: \"{lab}\" "
                       f"{{style.fill: '{fill}'; style.bold: true{mult}}}")

    for k in g.children[""]:
        emit(k, "")
    for e in g.edges:
        arrow = "<->" if e.bidir else "->"
        width = {"bus": 3, "data": 2}.get(e.cls, 1)
        dash = "; style.stroke-dash: 4; style.stroke: '#2e5aa8'" if e.cls == "control" else ""
        out.append(f"{path(e.a)} {arrow} {path(e.b)}: {{style.stroke-width: {width}{dash}}}")
    return "\n".join(out) + "\n"


def draw(g: PGraph, engine: str, out_svg) -> str:
    layout = {"d2_dagre": "dagre", "d2_elk": "elk", "d2_tala": "tala", "d2_grid": "dagre"}[engine]
    src = source(g, grid=engine == "d2_grid")
    d2 = p3lib.need(p3lib.D2, "d2")
    src_path = out_svg.with_suffix(".d2")
    src_path.write_text(src)
    p3lib.run([d2, f"--layout={layout}", "--pad=20", str(src_path), str(out_svg)], "", 300)
    return out_svg.read_text()
