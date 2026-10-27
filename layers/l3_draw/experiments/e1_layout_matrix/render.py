"""SVG output and the round-trip check (design-space Q2).

Every drawn element carries `data-rtl2d-kind` and `data-rtl2d-id`, as the L3 rules ask.
`roundtrip()` parses the SVG text back and compares it with the Diagram: same blocks,
same ports, every (net, sink) present as a wire or as a pair of stubs, and every wire
starting and ending on the port squares it names.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from html import escape as esc

from metrics import EPS, net_segments
from model import GLOBAL, Layout, Scene, U, norm, short

COLORS = {"data": "#1a1a1a", "control": "#1f5fbf", "status": "#1f5fbf", "clock": "#888",
          "reset": "#888", "bus": "#7a3fa0"}
STUB = 2.0  # stub length in units


def _attr(kind: str, rid: str, **more: str) -> str:
    extra = "".join(f' data-rtl2d-{k}="{esc(v)}"' for k, v in more.items())
    return f'data-rtl2d-kind="{kind}" data-rtl2d-id="{esc(rid)}"{extra}'


def _junctions(lay: Layout) -> list[tuple[float, float]]:
    """Points where three or more wire ends of one net meet (branch points)."""
    out = []
    for h, v, _d in net_segments(lay).values():
        for x, a, b in v:
            for y, c, d in h:
                on_h = c - EPS <= x <= d + EPS
                on_v = a - EPS <= y <= b + EPS
                if not (on_h and on_v):
                    continue
                arms = (x > c + EPS) + (x < d - EPS) + (y > a + EPS) + (y < b - EPS)
                if arms >= 3:
                    out.append((x, y))
    return out


def render(sc: Scene, lay: Layout, title: str = "") -> str:
    xs, ys = [0.0], [0.0]
    for n in lay.pos:
        r = lay.rect(sc, n)
        xs += [r.x, r.x2]
        ys += [r.y, r.y2]
    for r in lay.boxes.values():
        xs += [r.x, r.x2]
        ys += [r.y, r.y2]
    for pts in lay.wires.values():
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]
    if len(xs) == 1:
        xs, ys = [0.0, 20.0], [0.0, 6.0]
    else:
        xs, ys = xs[1:], ys[1:]
    x0, y0 = min(xs) - 5, min(ys) - 3
    w, h = (max(xs) - x0 + 5) * U, (max(ys) - y0 + 5) * U

    def X(v: float) -> str:
        return f"{(v - x0) * U:.1f}"

    def Y(v: float) -> str:
        return f"{(v - y0) * U:.1f}"

    o = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
        f'viewBox="0 0 {w:.0f} {h:.0f}" font-family="sans-serif" font-size="11">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for cid, r in lay.boxes.items():
        o.append(
            f'<g {_attr("block", cid)}><rect x="{X(r.x)}" y="{Y(r.y)}" width="{r.w * U:.1f}" '
            f'height="{r.h * U:.1f}" fill="#f5f6f8" stroke="#555" stroke-dasharray="5 3"/>'
            f'<text x="{float(X(r.x)) + 5:.1f}" y="{float(Y(r.y)) + 13:.1f}" font-weight="bold">'
            f"{esc(sc.blocks[cid].label)}</text></g>"
        )

    for (net, target), pts in lay.wires.items():
        n = next(x for x in sc.nets if x.id == net)
        c = norm(n.class_)
        color = COLORS.get(c, COLORS["data"])
        dash = ' stroke-dasharray="4 2"' if c in GLOBAL else ""
        d = "M" + " L".join(f"{X(x)} {Y(y)}" for x, y in pts)
        o.append(
            f'<path {_attr("wire", net, source=n.source, target=target)} d="{d}" fill="none" '
            f'stroke="{color}" stroke-width="{2 if n.width > 1 else 1}"{dash}/>'
        )
    for x, y in _junctions(lay):
        o.append(f'<circle cx="{X(x)}" cy="{Y(y)}" r="2.5" fill="#1a1a1a"/>')

    for bid in sc.leaves:
        if bid not in lay.pos:
            continue
        r = lay.rect(sc, bid)
        b = sc.blocks[bid]
        kind = norm(b.kind)
        if kind == "mux":
            cut = min(r.h / 4, 2)
            pts = [(r.x, r.y), (r.x2, r.y + cut), (r.x2, r.y2 - cut), (r.x, r.y2)]
            at = " ".join(f"{X(x)},{Y(y)}" for x, y in pts)
            shape = f'<polygon points="{at}" fill="white" stroke="#1a1a1a" stroke-width="1.5"/>'
        else:
            fill = "#eef3fb" if kind == "register" else "white"
            shape = (f'<rect x="{X(r.x)}" y="{Y(r.y)}" width="{r.w * U:.1f}" '
                     f'height="{r.h * U:.1f}" fill="{fill}" stroke="#1a1a1a" stroke-width="1.5"/>')
        lines = (b.label or "").split("\n")
        cx, cy = float(X(r.x + r.w / 2)), float(Y(r.y + r.h / 2)) + 4 - 6 * (len(lines) - 1)
        text = "".join(
            f'<text x="{cx:.1f}" y="{cy + 12 * i:.1f}" text-anchor="middle">{esc(t)}</text>'
            for i, t in enumerate(lines)
        )
        o.append(f'<g {_attr("block", bid)}>{shape}{text}</g>')

    for pid, (px, py) in lay.port_xy.items():
        p = sc.ports[pid]
        o.append(
            f'<rect {_attr("port", pid)} x="{float(X(px)) - 2:.1f}" y="{float(Y(py)) - 2:.1f}" '
            f'width="4" height="4" fill="{"white" if p.direction == "input" else "#1a1a1a"}" '
            f'stroke="#1a1a1a"/>'
        )
        if pid in sc.pins:
            r = lay.rect(sc, pid)
            o.append(f'<text x="{float(X(r.x + r.w / 2)):.1f}" y="{float(Y(r.y + 1)) + 4:.1f}" '
                     f'text-anchor="middle" font-size="10">{esc(short(pid))}</text>')

    implicit = []
    for n in sc.nets:
        mode = sc.hidden.get(n.id)
        if not mode:
            continue
        if mode == "implicit":
            implicit.append(short(n.id))
        color = COLORS.get(norm(n.class_), COLORS["data"])
        for pid in (n.source, *n.targets):
            if pid not in lay.port_xy:
                continue
            x, y = lay.port_xy[pid]
            dx, dy = {"W": (-1, 0), "E": (1, 0), "N": (0, -1), "S": (0, 1)}[sc.side[pid]]
            if mode == "implicit":
                o.append(f'<circle {_attr("implicit", n.id, port=pid)} cx="{X(x)}" cy="{Y(y)}" '
                         f'r="3" fill="{color}"/>')
                continue
            ex, ey = x + dx * STUB, y + dy * STUB
            anchor = "end" if dx < 0 else "start"
            tx = float(X(ex)) + (3 * dx if dx else 3)
            ty = float(Y(ey)) + (3 if dx else 4 * dy)
            o.append(
                f'<g {_attr("stub", n.id, port=pid)}><path d="M{X(x)} {Y(y)} L{X(ex)} {Y(ey)}" '
                f'stroke="{color}" fill="none"/><text x="{tx:.1f}" y="{ty:.1f}" font-size="9" '
                f'text-anchor="{anchor}" fill="{color}">{esc(short(n.id))}</text></g>'
            )
    foot = title + ("   not drawn as lines: " + ", ".join(implicit) if implicit else "")
    if foot:
        o.append(f'<text x="6" y="{h - 6:.0f}" font-size="10" fill="#666">{esc(foot)}</text>')
    o.append("</svg>")
    return "\n".join(o)


def roundtrip(sc: Scene, svg: str) -> list[str]:
    """Differences between the SVG and the Diagram; empty means the drawing is faithful."""
    root = ET.fromstring(svg)
    blocks, ports, wires, marks = set(), {}, [], set()
    for el in root.iter():
        kind, rid = el.get("data-rtl2d-kind"), el.get("data-rtl2d-id")
        if kind == "block":
            blocks.add(rid)
        elif kind == "port":
            ports[rid] = (float(el.get("x")) + 2, float(el.get("y")) + 2)
        elif kind == "wire":
            nums = el.get("d").replace("M", "").replace("L", " ").split()
            pts = [(float(a), float(b)) for a, b in zip(nums[::2], nums[1::2], strict=True)]
            wires.append((rid, el.get("data-rtl2d-source"), el.get("data-rtl2d-target"), pts))
        elif kind in ("stub", "implicit"):
            marks.add((rid, el.get("data-rtl2d-port")))
    issues = []
    want_blocks = {b.id for b in sc.d.blocks}
    if blocks != want_blocks:
        issues.append(f"blocks differ: missing {sorted(want_blocks - blocks)[:3]}, "
                      f"extra {sorted(blocks - want_blocks)[:3]}")
    want_ports = {p.id for p in sc.d.ports}
    if set(ports) != want_ports:
        issues.append(f"ports differ: missing {sorted(want_ports - set(ports))[:3]}, "
                      f"extra {sorted(set(ports) - want_ports)[:3]}")
    drawn = {(net, t) for net, _s, t, _p in wires}
    for n in sc.d.nets:
        for t in n.targets:
            as_wire = (n.id, t) in drawn
            as_mark = (n.id, n.source) in marks and (n.id, t) in marks
            if not (as_wire or as_mark):
                issues.append(f"net {n.id} -> {t} is not drawn")
    known = {(n.id, n.source, t) for n in sc.d.nets for t in n.targets}
    for net, s, t, pts in wires:
        if (net, s, t) not in known:
            issues.append(f"wire {net} {s} -> {t} is not in the diagram")
            continue
        for pid, pt in ((s, pts[0]), (t, pts[-1])):
            if pid in ports and max(abs(ports[pid][0] - pt[0]), abs(ports[pid][1] - pt[1])) > 1:
                issues.append(f"wire {net} does not end on port {pid}")
    return issues
