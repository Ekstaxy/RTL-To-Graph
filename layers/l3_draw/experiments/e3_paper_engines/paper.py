"""Paper-figure renderer (memo §2.1): the look of ISSCC / VLSI / MICRO architecture figures.

- top-level containers are subsystems: a pastel fill, a darker border and a bold title;
  nested containers are white with the same hue, dashed;
- units are rounded boxes filled by role (memory green, control orange, CPU yellow, I/O
  grey, compute blue); replicated units / containers are stacked with "xN";
- buses / crossbars / NoCs are bars;
- one arrow per pair of blocks, double-headed for read/write pairs; buses thick, data
  medium, control thin dashed; no clock or reset;
- terminals sit on the chip border with a pad symbol;
- a legend for the colours.
Every element carries data-rtl2d-kind / data-rtl2d-id; an edge also lists the Diagram
(net, sink) pairs it stands for in data-rtl2d-members (check.py reads them back).
"""

from __future__ import annotations

from html import escape as esc

from grammar import PGraph, wrap
from layout import Place

SUBSYS = [("#e6f2e1", "#5b9a4a"), ("#ececec", "#7a7a7a"), ("#f8e3e1", "#b5524a"),
          ("#e1ecf7", "#4a78b5"), ("#fbecd9", "#c27c2c"), ("#ece4f3", "#7d5aa6"),
          ("#e3f3f3", "#3e9696"), ("#f5f0d8", "#9a8a3a")]
CAT = {"memory": ("#dcefd4", "Memory"), "control": ("#fbdcc0", "Control"),
       "cpu": ("#fff0a8", "CPU"), "io": ("#e4e4e4", "I/O"),
       "compute": ("#d6e5f6", "Compute")}
STROKE = {"bus": (2.4, "#2b2b2b", ""), "data": (1.6, "#2b2b2b", ""),
          "control": (1.2, "#2e5aa8", ' stroke-dasharray="5 3"')}


def _a(kind: str, rid: str, **more: str) -> str:
    extra = "".join(f' data-rtl2d-{k}="{esc(v)}"' for k, v in more.items())
    return f'data-rtl2d-kind="{kind}" data-rtl2d-id="{esc(rid)}"{extra}'


def render(g: PGraph, pl: Place, routes: dict, title: str = "") -> str:
    xs, ys = [], []
    for k, (x, y) in pl.pos.items():
        n = g.nodes[k]
        xs += [x, x + n.w]
        ys += [y, y + n.h]
    for x, y, w, h in pl.boxes.values():
        xs += [x, x + w + 10]
        ys += [y - 10, y + h]
    for pts in routes.values():
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]
    x0, y0 = min(xs) - 30, min(ys) - 30
    W, H = max(xs) - x0 + 30, max(ys) - y0 + 90
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
         f'viewBox="{x0:.0f} {y0:.0f} {W:.0f} {H:.0f}" font-family="Helvetica, Arial, sans-serif">',
         "<defs>"
         '<marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" '
         'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
         '<path d="M0,0 L10,5 L0,10 z" fill="#2b2b2b"/></marker>'
         '<marker id="ahc" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
         'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
         '<path d="M0,0 L10,5 L0,10 z" fill="#2e5aa8"/></marker>'
         '<linearGradient id="bar" x1="0" y1="0" x2="0" y2="1">'
         '<stop offset="0" stop-color="#f4f4f4"/>'
         '<stop offset="1" stop-color="#bdbdbd"/></linearGradient>'
         '</defs>',
         f'<rect x="{x0:.0f}" y="{y0:.0f}" width="{W:.0f}" height="{H:.0f}" fill="white"/>']

    def hue(cid: str) -> tuple[str, str]:
        top = g.top_of(cid)
        return SUBSYS[g.colour_of.get(top, 0) % len(SUBSYS)]

    def depth(c: str) -> int:
        return len(g.chain(c))

    for cid in sorted(pl.boxes, key=depth):
        x, y, w, h = pl.boxes[cid]
        n = g.nodes[cid]
        fill, line = hue(cid)
        nested = depth(cid) > 0
        f = "white" if nested else fill
        dash = ' stroke-dasharray="6 3"' if nested else ""
        stack = ""
        if n.count > 1:
            for d in (10, 5):
                stack += (f'<rect x="{x + d:.1f}" y="{y - d:.1f}" width="{w:.1f}" height="{h:.1f}" '
                          f'rx="6" fill="{f}" stroke="{line}" stroke-width="1.2"/>')
        fs = 13 if not nested else 12
        o.append(f'<g {_a("block", cid)}>{stack}<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" '
                 f'height="{h:.1f}" rx="6" fill="{f}" stroke="{line}" stroke-width="1.6"{dash}/>'
                 f'<text x="{x + 10:.1f}" y="{y + 19:.1f}" font-size="{fs}" font-weight="bold" '
                 f'fill="{line}">{esc(n.label)}</text></g>')

    for e in g.edges:
        pts = routes.get(e.id)
        if not pts:
            continue
        sw, col, dash = STROKE.get(e.cls, STROKE["data"])
        mk = "ahc" if e.cls == "control" else "ah"
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        start = f' marker-start="url(#{mk})"' if e.bidir else ""
        members = ";".join(f"{a}|{b}" for a, b in e.members)
        o.append(f'<path {_a("edge", e.id, a=e.a, b=e.b, members=members)} d="{d}" fill="none" '
                 f'stroke="{col}" stroke-width="{sw}"{dash} marker-end="url(#{mk})"{start}/>')

    for k in sorted(pl.pos):
        n = g.nodes[k]
        x, y = pl.pos[k]
        if n.kind == "pin":
            left = x < (x0 + W / 2)
            px = x + n.w - 2 if left else x + 2
            lab_x = x + n.w - 16 if left else x + 16
            anchor = "end" if left else "start"
            o.append(f'<g {_a("port", k)}><rect x="{px - 6:.1f}" y="{y + n.h / 2 - 6:.1f}" '
                     f'width="12" height="12" fill="white" stroke="#333"/><path d="M{px - 6:.1f},'
                     f'{y + n.h / 2 - 6:.1f} l12,12 m0,-12 l-12,12" stroke="#333"/>'
                     f'<text x="{lab_x:.1f}" y="{y + n.h / 2 + 4:.1f}" font-size="11" '
                     f'text-anchor="{anchor}">{esc(n.label)}</text></g>')
            continue
        lines = [n.label] if n.kind == "bar" else wrap(n.label)
        cy = y + n.h / 2 - 8 * (len(lines) - 1) + 4
        text = "".join(f'<tspan x="{x + n.w / 2:.1f}" y="{cy + 16 * i:.1f}">{esc(s)}</tspan>'
                       for i, s in enumerate(lines))
        if n.kind == "bar":
            o.append(f'<g {_a("block", k)}><rect x="{x:.1f}" y="{y:.1f}" width="{n.w:.1f}" '
                     f'height="{n.h:.1f}" fill="url(#bar)" stroke="#333" stroke-width="1.4"/>'
                     f'<text font-size="12" font-weight="bold" text-anchor="middle">{text}'
                     f'</text></g>')
            continue
        fill = CAT.get(n.cat, CAT["compute"])[0]
        stack = ""
        if n.count > 1:
            for d in (8, 4):
                stack += (f'<rect x="{x + d:.1f}" y="{y - d:.1f}" width="{n.w:.1f}" '
                          f'height="{n.h:.1f}" rx="4" fill="{fill}" stroke="#444" '
                          f'stroke-width="1"/>')
        shadow = (f'<rect x="{x + 2:.1f}" y="{y + 2:.1f}" width="{n.w:.1f}" height="{n.h:.1f}" '
                  f'rx="4" fill="#000" fill-opacity="0.12"/>')
        o.append(f'<g {_a("block", k)}>{stack}{shadow}<rect x="{x:.1f}" y="{y:.1f}" '
                 f'width="{n.w:.1f}" height="{n.h:.1f}" rx="4" fill="{fill}" stroke="#444" '
                 f'stroke-width="1.2"/><text font-size="12" font-weight="600" '
                 f'text-anchor="middle">{text}</text></g>')

    # legend
    ly = y0 + H - 40
    lx = x0 + 20
    used = sorted({n.cat for n in g.nodes.values() if n.kind == "leaf"})
    items = [(CAT[c][0], CAT[c][1]) for c in used if c in CAT]
    leg = []
    for fill, name in items:
        leg.append(f'<rect x="{lx:.1f}" y="{ly:.1f}" width="14" height="14" rx="2" fill="{fill}" '
                   f'stroke="#444"/><text x="{lx + 20:.1f}" y="{ly + 11:.1f}" '
                   f'font-size="11">{name}</text>')
        lx += 30 + len(name) * 6.5
    lx += 20
    for txt, (sw, col, dash) in (("bus", STROKE["bus"]), ("data", STROKE["data"]),
                                 ("control", STROKE["control"])):
        leg.append(f'<path d="M{lx:.1f},{ly + 7:.1f} h28" stroke="{col}" '
                   f'stroke-width="{sw}"{dash}/>'
                   f'<text x="{lx + 34:.1f}" y="{ly + 11:.1f}" font-size="11">{txt}</text>')
        lx += 80
    o.append("<g>" + "".join(leg) + "</g>")
    if title:
        o.append(f'<text x="{x0 + 20:.1f}" y="{ly + 32:.1f}" font-size="10" fill="#888">'
                 f'{esc(title)}</text>')
    o.append("</svg>")
    return "\n".join(o)
