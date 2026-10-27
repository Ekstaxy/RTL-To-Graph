"""Readability measures of a WaveDrom timing SVG (as tagged by wave_draw).

    uv run --package rtl2d-l3 python \
        layers/l3_draw/experiments/e4_fsm_timing_draw/wave_measure.py OUT.svg OUT.wavedrom.json

Returns width/height (px), lanes, arrows, label collisions (estimated text boxes of data /
gap labels that overlap each other), label overflows (a data label wider than its segment,
from the WaveDrom source), arrow crossings (pairs of arrow paths that intersect away from their
ends), arrows through labels, and the shown / hidden cycles per domain.
Text extents are estimated (CHAR_PX per character), not measured.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from itertools import combinations
from pathlib import Path

NS = "{http://www.w3.org/2000/svg}"
CHAR_PX = 7.6
LABEL_PAD = 12
TOK = re.compile(r"[MmCcLl]|-?\d+(?:\.\d+)?(?:e-?\d+)?")
Box = tuple[float, float, float, float]


def _translate(el: ET.Element) -> tuple[float, float]:
    m = re.search(r"translate\(\s*(-?[\d.]+)(?:[ ,]\s*(-?[\d.]+))?", el.get("transform", ""))
    if not m:
        return 0.0, 0.0
    return float(m.group(1)), float(m.group(2) or 0)


def walk(el: ET.Element, ox: float = 0.0, oy: float = 0.0, up: tuple = ()):
    """Yield (element, absolute offset, ancestor chain) for every element."""
    dx, dy = _translate(el)
    ox, oy = ox + dx, oy + dy
    yield el, ox, oy, up
    for k in el:
        yield from walk(k, ox, oy, (*up, el))


def text_box(el: ET.Element, ox: float, oy: float) -> Box | None:
    txt = "".join(el.itertext()).strip()
    if not txt:
        return None
    x, y = float(el.get("x", 0)), float(el.get("y", 0))
    w = CHAR_PX * len(txt)
    a = el.get("text-anchor", "start")
    x0 = ox + x - (w / 2 if a == "middle" else (w if a == "end" else 0))
    return (x0, oy + y - 11, x0 + w, oy + y + 3)


def _overlap(a: Box, b: Box) -> bool:
    return a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1


def path_points(d: str, ox: float, oy: float) -> list[tuple[float, float]]:
    """Flatten M/m/L/l/C/c paths (WaveDrom arcs) to absolute points."""
    toks = TOK.findall(d)
    pts: list[tuple[float, float]] = []
    cmd, cur, i = "M", (0.0, 0.0), 0
    while i < len(toks):
        if toks[i] in "MmCcLl":
            cmd = toks[i]
            i += 1
            continue
        n = 6 if cmd in "Cc" else 2
        v = [float(x) for x in toks[i:i + n]]
        i += n
        if len(v) < n:
            break
        rel = cmd.islower() and pts
        bx, by = cur if rel else (0.0, 0.0)
        if cmd in "Cc":
            p1, p2, p3 = (bx + v[0], by + v[1]), (bx + v[2], by + v[3]), (bx + v[4], by + v[5])
            for k in range(1, 9):
                t = k / 8
                a, b, c, e = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
                pts.append((a * cur[0] + b * p1[0] + c * p2[0] + e * p3[0],
                            a * cur[1] + b * p1[1] + c * p2[1] + e * p3[1]))
            cur = p3
        else:
            cur = (bx + v[0], by + v[1])
            pts.append(cur)
    return [(x + ox, y + oy) for x, y in pts]


def _seg_x(a, b, c, d) -> tuple[float, float] | None:
    r, s = (b[0] - a[0], b[1] - a[1]), (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    return (a[0] + t * r[0], a[1] + t * r[1]) if 0 <= t <= 1 and 0 <= u <= 1 else None


def _cross(pa: list, pb: list, eps: float = 6.0) -> bool:
    ends = [pa[0], pa[-1], pb[0], pb[-1]]
    for a, b in zip(pa, pa[1:], strict=False):
        for c, d in zip(pb, pb[1:], strict=False):
            p = _seg_x(a, b, c, d)
            if p and all(abs(p[0] - e[0]) + abs(p[1] - e[1]) > eps for e in ends):
                return True
    return False


def _overflows(wj: dict) -> int:
    grid = wj["rtl2d"]["grid"]
    px = grid["px_per_unit"]
    n = 0
    sigs = [x for s in wj["signal"] for x in (s[1:] if isinstance(s, list) else [s])
            if isinstance(x, dict)]
    for sig in sigs:
        data, seg, inside = list(sig.get("data") or []), [], False
        for ch in sig.get("wave", ""):
            if ch == "=":
                seg.append(1)
                inside = True
            elif ch in ".|" and inside:
                seg[-1] += 1
            else:
                inside = False
        per = sig.get("period", 1)
        n += sum(CHAR_PX * len(t) + LABEL_PAD > k * per * px + 0.5
                 for t, k in zip(data, seg, strict=False))
    return n


def _cycles(wj: dict) -> dict:
    out: dict[str, dict] = {}
    for m in wj["rtl2d"]["signals"]:
        if m["kind"] == "clock":
            out[m["domain"]] = {"shown": sum(1 for c in m["cols"] if c[0] == "s"),
                                "drawn_columns": len(m["cols"])}
    for g in wj["rtl2d"]["gaps"]:
        for did, n in (g.get("hidden") or {}).items():
            if did in out:
                out[did]["hidden"] = out[did].get("hidden", 0) + n
    return out


def measure(svg_text: str, wavejson: dict | None = None) -> dict:
    root = ET.fromstring(svg_text)
    labels: list[Box] = []
    arrows: list[list] = []
    for el, ox, oy, up in walk(root):
        anc = {a.get("id", "") for a in up}
        kind = el.get("data-rtl2d-kind")
        if el.tag == f"{NS}text" and any(a.startswith(("wavelane_draw_", "wavearcs_"))
                                         for a in anc):
            b = text_box(el, ox, oy)
            if b:
                labels.append(b)
        elif kind == "arrow" and el.tag == f"{NS}path":
            pts = path_points(el.get("d", ""), ox, oy)
            if len(pts) > 1:
                arrows.append(pts)
    collide = sum(_overlap(a, b) for a, b in combinations(labels, 2))
    cross = sum(_cross(a, b) for a, b in combinations(arrows, 2))
    through = sum(1 for p in arrows for b in labels
                  if any(b[0] < x < b[2] and b[1] < y < b[3] for x, y in p[1:-1]))
    out = {"width": float(root.get("width", 0)), "height": float(root.get("height", 0)),
           "lanes": sum(1 for e in root.iter() if e.get("data-rtl2d-kind") == "lane"),
           "arrows": len(arrows), "label_collisions": collide, "arrow_crossings": cross,
           "arrows_through_labels": through}
    if wavejson is not None:
        out["label_overflows"] = _overflows(wavejson)
        out["cycles"] = _cycles(wavejson)
        out["grid"] = {k: wavejson["rtl2d"]["grid"][k] for k in ("unit", "hscale", "skin")}
    return out


def main(argv: list[str]) -> int:
    svg = Path(argv[0]).read_text(encoding="utf-8")
    wj = json.loads(Path(argv[1]).read_text(encoding="utf-8")) if len(argv) > 1 else None
    print(json.dumps(measure(svg, wj), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
