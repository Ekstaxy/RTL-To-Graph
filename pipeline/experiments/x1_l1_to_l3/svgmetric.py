"""Renderer-independent wire metrics from an SVG whose wires carry data-rtl2d-id (L3's
convention, also used by paper.py): crossings between different nets, collinear overlaps
between different nets, bends, total wire length (per-net union)."""

import re
import sys
from collections import defaultdict
from pathlib import Path


def segments(svg: str):
    segs = defaultdict(set)
    for m in re.finditer(r'<path[^>]*data-rtl2d-kind="wire"[^>]*>', svg):
        tag = m.group(0)
        nid = re.search(r'data-rtl2d-id="([^"]*)"', tag).group(1)
        d = re.search(r' d="([^"]*)"', tag).group(1)
        pts = [tuple(map(float, xy)) for xy in re.findall(r"(-?[\d.]+)[ ,](-?[\d.]+)", d)]
        for a, b in zip(pts, pts[1:], strict=False):
            if a != b:
                segs[nid].add((min(a, b), max(a, b)))
    return segs


def blocks(svg: str) -> dict:
    """Block id -> bbox (x0, y0, x1, y1): data-rtl2d-bbox if present (paper.py), else the
    first rect / polygon inside the block group (L3)."""
    out = {}
    for m in re.finditer(r'<g data-rtl2d-kind="block"([^>]*)>(.*?)</g>', svg, re.S):
        attrs, body = m.group(1), m.group(2)
        bid = re.search(r'data-rtl2d-id="([^"]*)"', attrs).group(1)
        bb = re.search(r'data-rtl2d-bbox="([^"]*)"', attrs)
        if bb:
            x, y, w, h = map(float, bb.group(1).split())
        else:
            r = re.search(
                r'<rect[^>]* x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" '
                r'height="([-\d.]+)"',
                body,
            )
            if r:
                x, y, w, h = map(float, r.groups())
            else:
                pg = re.search(r'points="([^"]*)"', body)
                if not pg:
                    continue
                pts = [tuple(map(float, q.split(","))) for q in pg.group(1).split()]
                xs, ys = [q[0] for q in pts], [q[1] for q in pts]
                x, y, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        out[bid] = (x, y, x + w, y + h)
    return out


def through(segs: dict, bboxes: dict, eps: float = 1.5) -> int:
    """Wire segments whose interior runs inside a block (shrunk by eps)."""
    n = 0
    for ss in segs.values():
        for a, b in ss:
            for x0, y0, x1, y1 in bboxes.values():
                x0, y0, x1, y1 = x0 + eps, y0 + eps, x1 - eps, y1 - eps
                if abs(a[1] - b[1]) < 0.01:  # horizontal
                    if y0 < a[1] < y1 and min(b[0], x1) - max(a[0], x0) > 0:
                        n += 1
                elif abs(a[0] - b[0]) < 0.01:
                    if x0 < a[0] < x1 and min(b[1], y1) - max(a[1], y0) > 0:
                        n += 1
    return n


def _merge(ss):
    """Per net: merge collinear overlapping segments -> (horizontals, verticals)."""
    hs, vs = {}, {}
    for a, b in ss:
        if abs(a[1] - b[1]) < 0.5:
            hs.setdefault(round(a[1], 1), []).append((min(a[0], b[0]), max(a[0], b[0])))
        elif abs(a[0] - b[0]) < 0.5:
            vs.setdefault(round(a[0], 1), []).append((min(a[1], b[1]), max(a[1], b[1])))

    def join(d):
        out = []
        for k, iv in d.items():
            iv.sort()
            lo, hi = iv[0]
            for x0, x1 in iv[1:]:
                if x0 <= hi + 0.5:
                    hi = max(hi, x1)
                else:
                    out.append((k, lo, hi))
                    lo, hi = x0, x1
            out.append((k, lo, hi))
        return out

    return join(hs), join(vs)


def bends(segs: dict) -> dict:
    """Corners per net, and how many are avoidable on two-pin nets.

    A corner is a point where one horizontal and one vertical run of the same net end (not a
    T-junction). For a two-pin net whose pins both leave sideways, the minimum is 0 when the
    pins are level and 2 (a Z) otherwise; one up/down pin makes it 1. `excess` counts corners
    above that minimum; `jog` counts Z-shapes with a rise under 16 px, which moving a block or
    boundary port by that much would straighten."""
    corners = excess = jogs = two_pin = 0
    detours = []
    for ss in segs.values():
        H, V = _merge(ss)
        ends, way = {}, {}  # way: direction from a leaf into its wire (+1 / -1)
        for y, x0, x1 in H:
            for pt, d in (((round(x0, 1), y), 1), ((round(x1, 1), y), -1)):
                ends.setdefault(pt, []).append("H")
                way[pt] = d
        for x, y0, y1 in V:
            for pt, d in (((x, round(y0, 1)), 1), ((x, round(y1, 1)), -1)):
                ends.setdefault(pt, []).append("V")
                way[pt] = d

        def inside(pt, H=H, V=V):
            x, y = pt
            return any(abs(y - hy) < 0.5 and x0 + 0.5 < x < x1 - 0.5 for hy, x0, x1 in H) or any(
                abs(x - vx) < 0.5 and y0 + 0.5 < y < y1 - 0.5 for vx, y0, y1 in V
            )

        c = sum(1 for pt, k in ends.items() if sorted(k) == ["H", "V"] and not inside(pt))
        leaves = [(pt, k[0]) for pt, k in ends.items() if len(k) == 1 and not inside(pt)]
        corners += c
        if len(leaves) >= 2:
            xs = [pt[0] for pt, _ in leaves]
            ys = [pt[1] for pt, _ in leaves]
            hpwl = (max(xs) - min(xs)) + (max(ys) - min(ys))
            ln = sum(x1 - x0 for _, x0, x1 in H) + sum(y1 - y0 for _, y0, y1 in V)
            if hpwl > 1:
                detours.append(ln / hpwl)
        if len(leaves) == 2:
            two_pin += 1
            (p1, o1), (p2, o2) = leaves
            dy, dx = abs(p1[1] - p2[1]), abs(p1[0] - p2[0])
            if o1 == o2:  # both pins sideways (H) or both up/down (V)
                ax = 0 if o1 == "H" else 1
                a, b = sorted([p1, p2], key=lambda q: q[ax])
                rise = dy if o1 == "H" else dx
                if way[a] == 1 and way[b] == -1:  # facing each other: straight or a Z
                    lb = 0 if rise < 1 else 2
                elif way[a] == -1 and way[b] == 1:  # facing away: must go around, 4
                    lb = 4
                else:  # same direction: a C shape
                    lb = 2
            else:
                lb = 1
            excess += max(0, c - lb)
            if lb == 2 and c == 2 and (dy if o1 == "H" else dx) < 16:
                jogs += 1
    detours.sort()
    return {
        "bends": corners,
        "bend_excess": excess,
        "small_jogs": jogs,
        "two_pin": two_pin,
        "detour_med": round(detours[len(detours) // 2], 2) if detours else None,
    }


def labels(svg: str) -> list:
    """Approximate text boxes: (x0, y0, x1, y1), from x/y, text-anchor and font-size."""
    out = []
    for m in re.finditer(r"<text([^>]*)>([^<]*)</text>", svg):
        attrs, txt = m.group(1), m.group(2)
        x = float(re.search(r' x="([-\d.]+)"', attrs).group(1))
        y = float(re.search(r' y="([-\d.]+)"', attrs).group(1))
        fs = re.search(r'font-size="([\d.]+)"', attrs)
        fs = float(fs.group(1)) if fs else 11.0
        w = len(txt) * fs * 0.55
        anchor = re.search(r'text-anchor="(\w+)"', attrs)
        anchor = anchor.group(1) if anchor else "start"
        x0 = x - w if anchor == "end" else x - w / 2 if anchor == "middle" else x
        out.append((x0, y - fs * 0.9, x0 + w, y + fs * 0.2))
    return out


def label_hits(svg: str) -> dict:
    """Readability proxies: labels crossed by a wire of another element, and labels that
    overlap another label."""
    segs = [(a, b) for ss in segments(svg).values() for a, b in ss]
    boxes = labels(svg)
    wire = text = 0
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        if any(
            (
                abs(a[1] - b[1]) < 0.01
                and y0 < a[1] < y1
                and min(a[0], b[0]) < x1
                and max(a[0], b[0]) > x0
            )
            or (
                abs(a[0] - b[0]) < 0.01
                and x0 < a[0] < x1
                and min(a[1], b[1]) < y1
                and max(a[1], b[1]) > y0
            )
            for a, b in segs
        ):
            wire += 1
        for j in range(i + 1, len(boxes)):
            u0, v0, u1, v1 = boxes[j]
            if x0 < u1 and u0 < x1 and y0 < v1 and v0 < y1:
                text += 1
    return {"labels": len(boxes), "label_wire": wire, "label_text": text}


def metrics(svg: str) -> dict:
    segs = segments(svg)
    hs = [(n, a, b) for n, ss in segs.items() for a, b in ss if abs(a[1] - b[1]) < 0.01]
    vs = [(n, a, b) for n, ss in segs.items() for a, b in ss if abs(a[0] - b[0]) < 0.01]
    cross = overlap = 0
    for n1, a, b in hs:
        for n2, c, d in vs:
            if n1 != n2 and a[0] + 0.5 < c[0] < b[0] - 0.5 and c[1] + 0.5 < a[1] < d[1] - 0.5:
                cross += 1
    for group, ax in ((hs, 1), (vs, 0)):
        o = 1 - ax
        for i, (n1, a, b) in enumerate(group):
            for n2, c, d in group[i + 1 :]:
                if n1 != n2 and abs(a[ax] - c[ax]) < 1.0 and min(b[o], d[o]) - max(a[o], c[o]) > 2:
                    overlap += 1
    length = sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for ss in segs.values() for a, b in ss)
    return {
        "through": through(segs, blocks(svg)),
        "nets": len(segs),
        "cross": cross,
        "overlap": overlap,
        "segments": sum(map(len, segs.values())),
        "length": round(length),
        **bends(segs),
        **label_hits(svg),
    }


if __name__ == "__main__":
    for f in sys.argv[1:]:
        print(f"{Path(f).name:50s}", metrics(Path(f).read_text(encoding="utf-8")))
