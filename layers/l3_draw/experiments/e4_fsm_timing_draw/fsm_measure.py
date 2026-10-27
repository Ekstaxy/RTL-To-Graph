"""Readability measures of a Graphviz FSM SVG (as written by fsm_draw).

    uv run --package rtl2d-l3 python \
        layers/l3_draw/experiments/e4_fsm_timing_draw/fsm_measure.py FSM.svg

Returns width/height (pt), node overlaps, edge crossings, edge-label overlaps (label vs label,
label vs state), label hits (another edge's line through a label), back edges (an LR drawing
whose edge ends left of where it starts; self-loops excluded) and self-loops, plus
score = (hard, crossings, label_overlaps, height) where hard = node overlaps.
Text extents are estimated (0.58 x font-size per character, Helvetica), not measured.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from itertools import combinations
from pathlib import Path

NS = "{http://www.w3.org/2000/svg}"
CHAR_W = 0.58
NUM = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?")
Box = tuple[float, float, float, float]  # x0, y0, x1, y1


def _num(s: str | None, default: float = 0.0) -> float:
    m = NUM.search(s or "")
    return float(m.group()) if m else default


def text_box(el: ET.Element) -> Box | None:
    txt = "".join(el.itertext()).strip()
    if not txt:
        return None
    fs = _num(el.get("font-size"), 14.0)
    x, y = _num(el.get("x")), _num(el.get("y"))
    w = CHAR_W * fs * len(txt)
    anchor = el.get("text-anchor", "start")
    x0 = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
    return (x0, y - 0.8 * fs, x0 + w, y + 0.2 * fs)


def _union(boxes: list[Box]) -> Box | None:
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _overlap(a: Box, b: Box, pad: float = 0.0) -> bool:
    return a[0] < b[2] - pad and b[0] < a[2] - pad and a[1] < b[3] - pad and b[1] < a[3] - pad


def node_box(g: ET.Element) -> Box | None:
    boxes: list[Box] = []
    for e in g.iter(f"{NS}ellipse"):
        cx, cy, rx, ry = (_num(e.get(k)) for k in ("cx", "cy", "rx", "ry"))
        boxes.append((cx - rx, cy - ry, cx + rx, cy + ry))
    for p in g.iter(f"{NS}polygon"):
        v = [float(x) for x in NUM.findall(p.get("points", ""))]
        if v:
            xs, ys = v[0::2], v[1::2]
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
    return _union(boxes)


def _bez(p0, p1, p2, p3, n: int = 8) -> list[tuple[float, float]]:
    out = []
    for i in range(1, n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                    a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def path_points(d: str) -> list[tuple[float, float]]:
    """Graphviz edge paths are 'M x,y C x1,y1 x2,y2 x3,y3 ...'; flatten the cubics."""
    v = [float(x) for x in NUM.findall(d)]
    pts = list(zip(v[0::2], v[1::2], strict=False))
    if not pts:
        return []
    out = [pts[0]]
    for i in range(1, len(pts) - 2, 3):
        out += _bez(out[-1], pts[i], pts[i + 1], pts[i + 2])
    return out


def _seg_x(a, b, c, d) -> tuple[float, float] | None:
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def _near(p, q, eps: float) -> bool:
    return abs(p[0] - q[0]) < eps and abs(p[1] - q[1]) < eps


def crossings(pa: list, pb: list, eps: float = 8.0) -> int:
    ends = [pa[0], pa[-1], pb[0], pb[-1]]
    hits: list[tuple[float, float]] = []
    for a, b in zip(pa, pa[1:], strict=False):
        for c, d in zip(pb, pb[1:], strict=False):
            p = _seg_x(a, b, c, d)
            if p and not any(_near(p, e, eps) for e in ends) and \
                    not any(_near(p, h, 2.0) for h in hits):
                hits.append(p)
    return len(hits)


def _line_hits_box(pts: list, box: Box) -> bool:
    return any(box[0] < x < box[2] and box[1] < y < box[3] for x, y in pts)


def _parse(root: ET.Element):
    nodes: dict[str, Box] = {}
    edges: list[dict] = []
    for g in root.iter(f"{NS}g"):
        cls, kind = g.get("class"), g.get("data-rtl2d-kind")
        if cls == "node":
            b = node_box(g)
            if b:
                nodes[g.get("data-rtl2d-id") or g.get("id") or str(len(nodes))] = b
        elif cls == "edge":
            p = g.find(f"{NS}path")
            pts = path_points(p.get("d", "")) if p is not None else []
            lab = _union([b for t in g.iter(f"{NS}text") if (b := text_box(t))])
            edges.append({"pts": pts, "label": lab, "kind": kind,
                          "src": g.get("data-rtl2d-src"), "dst": g.get("data-rtl2d-dst")})
    return nodes, edges


def measure(svg_text: str) -> dict:
    root = ET.fromstring(svg_text)
    nodes, edges = _parse(root)
    node_ov = sum(_overlap(a, b) for a, b in combinations(nodes.values(), 2))
    cross = sum(crossings(a["pts"], b["pts"]) for a, b in combinations(edges, 2)
                if len(a["pts"]) > 1 and len(b["pts"]) > 1)
    labels = [e["label"] for e in edges if e["label"]]
    lab_lab = sum(_overlap(a, b, 0.5) for a, b in combinations(labels, 2))
    lab_node = sum(_overlap(lb, nb, 0.5) for lb in labels for nb in nodes.values())
    lab_hit = sum(_line_hits_box(e["pts"], f["label"]) for e in edges for f in edges
                  if f is not e and f["label"])
    loops = sum(1 for e in edges if e["src"] and e["src"] == e["dst"])
    back = sum(1 for e in edges if e["kind"] == "transition" and e["src"] != e["dst"]
               and len(e["pts"]) > 1 and e["pts"][-1][0] < e["pts"][0][0] - 5)
    w, h = _num(root.get("width")), _num(root.get("height"))
    return {"width": w, "height": h, "states": sum(
        1 for g in root.iter(f"{NS}g") if g.get("data-rtl2d-kind") == "state"),
        "edges": len(edges), "node_overlaps": node_ov, "crossings": cross,
        "label_overlaps": lab_lab + lab_node, "label_label": lab_lab, "label_node": lab_node,
        "label_hits": lab_hit, "back_edges": back, "self_loops": loops,
        "score": [node_ov, cross, lab_lab + lab_node, h]}


def main(argv: list[str]) -> int:
    print(json.dumps(measure(Path(argv[0]).read_text(encoding="utf-8")), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
