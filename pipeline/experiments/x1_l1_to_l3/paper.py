"""Paper-style black-and-white renderer for pipelined datapaths (experiment, not L3 src).

Input: e0 diagram.json + hints.json (+ meta.json for shape kinds and stage names), as written
by bridge.py. Output: SVG. The drawing rules are in RULES.md (R1-R12); the code cites them.

Pipeline (all deterministic):
  1. columns  : stage k -> sub-columns by longest path inside the stage; pipeline register k ->
                one bar column between stage k and k+1 (R1, R2).
  2. ports    : sides by role (mux select / register enables on top, R4); pipeline register
                inputs and outputs paired into lanes that keep one y across the bar (R2, R11).
  3. y        : iterative median alignment of every block / lane to the ports it talks to,
                then order-preserving packing per column; control lane band on top (R6).
  4. routing  : forward = Z-route through the gap before the target column (corridor search
                when blocked); backward = up/down into a top/bottom channel (R7); tracks in
                gaps and channels by interval colouring; gap widths follow track counts.
  5. render   : shapes by kind (R3-R5), dashed control (R9), junction dots, arrowheads, bus
                width slashes, stage titles (R10).
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

PITCH = 16  # port spacing
TRACK = 7  # wire spacing in gaps / channels
GAP_MIN = 26
BAR_W = 12
VGAP = 26  # vertical space between blocks in one column
TITLED = ("memory", "control", "comb", "register")
SIZE = {  # kind -> width
    "mux": 26,
    "alu": 54,
    "adder": 40,
    "memory": 92,
    "register": 34,
    "pipeline_reg": BAR_W,
    "control": 84,
    "comb": 78,
    "split": 6,
}


class P:  # port
    def __init__(self, d):
        self.id, self.block, self.dir = d["id"], d["owner_block_id"], d["direction"]
        self.width, self.cls = d["width"], d["class"]
        self.name = d.get("name") or self.id.rsplit(".", 1)[-1]
        self.bundle = d.get("bundle", False)
        self.side = "L" if self.dir == "input" else "R"
        self.off = 0.0  # offset along its side from the block top (L/R) or left (T)
        self.nets: list = []
        self.lane = None  # pipeline register lane key


class B:  # block
    def __init__(self, d, kind, hint):
        self.id, self.label, self.kind = d["id"], d["label"], kind
        self.hint = hint
        self.ports: list[P] = []
        self.col = 0
        self.y = 0.0
        self.w = SIZE.get(kind, 70)
        self.h = 40.0
        self.band = 0 if hint.get("lane") == "control" else 1
        self.bar = False  # R6/R14: a wide thin bar spanning the columns it talks to
        self.span = (0, 0)
        self.x = None


def nice(label: str, kind: str) -> str:
    s = label.replace(" Plus", "+").replace("Plus", "+")
    s = re.sub(r"\bMUX\b", "", s).strip() if kind == "mux" else s
    return s


class Drawing:
    def __init__(self, diagram: dict, hints: dict, meta: dict):
        self.meta = meta
        kinds = meta["kinds"]
        hb = hints["blocks"]
        diagram = bundle(diagram, kinds, meta)
        self.blocks = {
            b["id"]: B(b, kinds.get(b["id"], b["kind"] or "comb"), hb.get(b["id"], {}))
            for b in diagram["blocks"]
        }
        self.ports = {p["id"]: P(p) for p in diagram["ports"]}
        for p in self.ports.values():
            if p.block:
                self.blocks[p.block].ports.append(p)
        self.nets = [n for n in diagram["nets"] if n["class"] not in ("clock", "reset")]  # R8
        for n in self.nets:
            for pid in [n["source"], *n["targets"]]:
                self.ports[pid].nets.append(n)
        self.feedback = set(hints.get("sinks", {}))
        ws = [n["width"] for n in self.nets if n["class"] == "data"]
        self.main_w = max(set(ws), key=ws.count) if ws else 0
        self.bound_out = [
            p for p in self.ports.values() if p.block is None and p.dir == "output" and p.nets
        ]
        self.bound_in = [
            p for p in self.ports.values() if p.block is None and p.dir == "input" and p.nets
        ]

    # ------------------------------------------------------------------ 1. columns (R1, R2)
    def columns(self):
        st = {b.id: b.hint.get("stage_index") for b in self.blocks.values()}
        nstage = 1 + max(
            [v for v in st.values() if v is not None]
            + [b.hint.get("stage_boundary", -1) + 1 for b in self.blocks.values()]
        )
        # longest path inside a stage over forward edges
        succ = defaultdict(set)
        for n in self.nets:
            sb = self.ports[n["source"]].block
            for t in n["targets"]:
                tb = self.ports[t].block
                if not (sb and tb) or sb == tb or f"{n['id']}|{t}" in self.feedback:
                    continue
                if st.get(sb) is not None and st.get(sb) == st.get(tb):
                    succ[sb].add(tb)
        layer = {}

        def depth(b, stack=()):
            if b in layer:
                return layer[b]
            preds = [a for a in succ if b in succ[a] and a not in stack]
            layer[b] = 1 + max((depth(a, stack + (b,)) for a in preds), default=-1)
            return layer[b]

        for b in self.blocks:
            if st[b] is not None:
                depth(b)
        # a block that only feeds a same-stage register goes right before it (PC mux -> PC)
        for b in self.blocks.values():
            outs = {
                self.ports[t].block
                for p in b.ports
                if p.dir == "output"
                for n in p.nets
                for t in n["targets"]
            }
            regs = [
                r for r in outs if r and self.blocks[r].kind == "register" and st[r] == st[b.id]
            ]
            if regs and len(outs) == 1:
                layer[b.id] = layer[regs[0]] - 1
        for s in range(nstage):
            ids = [b for b in self.blocks if st[b] == s]
            if ids:
                lo = min(layer[b] for b in ids)
                for b in ids:
                    layer[b] -= lo
        cols = []  # (kind, stage, layer)
        for s in range(nstage):
            n_l = 1 + max([layer[b] for b in self.blocks if st[b] == s], default=0)
            cols += [("st", s, i) for i in range(n_l)]
            if any(b.hint.get("stage_boundary") == s for b in self.blocks.values()):
                cols.append(("bar", s, 0))
        self.cols = cols
        for b in self.blocks.values():
            if "stage_boundary" in b.hint:
                b.col = cols.index(("bar", b.hint["stage_boundary"], 0))
            else:
                b.col = cols.index(("st", st[b.id] or 0, layer.get(b.id, 0)))
        self.nstage = nstage

    # ------------------------------------------------------------------ 2. ports (R2, R4)
    def sides(self):
        for b in self.blocks.values():
            ins = [p for p in b.ports if p.dir == "input" and p.nets]
            if b.kind == "mux":
                sel = min(ins, key=lambda p: p.width)
                sel.side = "T"
            if b.kind == "pipeline_reg":  # R2: lanes from the bridge's structural pairing
                pair = self.meta.get("lanes", {}).get(b.id, {})
                lane_of_in = {i: o for o, i in pair.items()}
                for p in b.ports:
                    if p.dir == "output":
                        p.lane = p.id
                    elif p.id in lane_of_in:
                        p.lane = lane_of_in[p.id]
                    elif p.width <= 2 and not p.bundle:
                        p.side = "T"  # enable / stall / flush
                    else:
                        p.lane = p.id
            if b.kind == "register":
                for p in ins:
                    if p.width <= 2 and p.cls == "control":
                        p.side = "T"
            tops = [p for p in b.ports if p.side == "T" and p.nets]
            for p in tops[max(1, int(b.w // 10)) :]:
                p.side = "L"  # no more top ports than fit
                if b.kind == "pipeline_reg":
                    p.lane = p.id
            b.ports = [p for p in b.ports if p.nets]
            if b.kind in TITLED or b.kind in ("alu", "adder"):
                lab = nice(b.label, b.kind)
                left = max([len(p.name) for p in b.ports if p.side == "L"], default=0)
                right = max([len(p.name) for p in b.ports if p.side == "R"], default=0)
                need = max(len(lab) * 6.2 + 14, (left + right) * 3.7 + 22)
                b.w = max(b.w, min(need, 220))
            nl = sum(p.side == "L" for p in b.ports)
            nr = sum(p.side == "R" for p in b.ports)
            b.h = max(2, nl, nr) * PITCH + 12
            if b.kind == "mux":
                b.h = max(nl, 2) * PITCH + 20
            if b.kind == "alu":
                b.h = max(b.h, 84)
            if b.kind in TITLED:
                b.h = max(b.h + 16, 52)
            if b.kind == "split":
                b.h = max(nl, nr) * PITCH + 4

    # ------------------------------------------------------------------ helpers
    def other_ends(self, p: P):
        for n in p.nets:
            ends = n["targets"] if p.dir == "output" else [n["source"]]
            for e in ends:
                yield self.ports[e], n

    def pxy(self, p: P):
        """Absolute endpoint of a port."""
        if p.block is None:
            return (self.in_x if p.dir == "input" else self.out_x, self.bound_y[p.id])
        b = self.blocks[p.block]
        x0 = self.bx(b)
        if p.side == "L":
            return (x0, b.y + p.off)
        if p.side == "R":
            return (x0 + b.w, b.y + p.off)
        return (x0 + p.off, b.y)

    def py(self, p: P) -> float:
        if p.block is None:
            return self.bound_y.get(p.id, 0.0)
        b = self.blocks[p.block]
        return b.y + (p.off if p.side in "LR" else 0)

    def layout_ports(self):
        """Order ports on each side by the y of what they connect to; lanes are shared."""
        for b in self.blocks.values():
            for side in "LR":
                ps = [p for p in b.ports if p.side == side]
                if b.kind == "pipeline_reg":
                    continue
                key = {p.id: _med([self.py(q) for q, _ in self.other_ends(p)] or [0]) for p in ps}
                ps.sort(key=lambda p: key[p.id])
                n = len(ps)
                if b.kind == "mux" and side == "L":
                    ps.sort(key=lambda p: p.name)  # d0, d1, d2 in order
                title = 16 if b.kind in TITLED else 0  # R10: block name row above ports
                top = title + (b.h - title - (n - 1) * PITCH) / 2
                for i, p in enumerate(ps):
                    p.off = top + i * PITCH
            tops = [p for p in b.ports if p.side == "T"]
            for i, p in enumerate(tops):
                p.off = b.w * (i + 1) / (len(tops) + 1)

    # ------------------------------------------------------------------ 3. y placement (R11)
    def place(self, iters: int = 40):
        bycol = defaultdict(list)
        for b in self.blocks.values():
            bycol[b.col].append(b)
        if getattr(self, "bars", False):
            self.mark_bars()
        y0 = 40.0
        for bs in bycol.values():
            y = y0
            for b in sorted(bs, key=lambda b: (b.band, b.id)):
                if not b.bar:
                    b.y, y = y, y + b.h + VGAP
        self.bound_y = {}
        for it in range(iters):
            self.layout_lanes()
            self.layout_ports()
            order = range(len(self.cols)) if it % 2 == 0 else reversed(range(len(self.cols)))
            for c in order:
                bs = [b for b in bycol.get(c, []) if b.kind != "pipeline_reg"]
                want = {}
                for b in bs:
                    vals = []
                    for p in b.ports:
                        if p.side == "T":
                            continue  # selects / enables do not pull the block (R4)
                        for q, n in self.other_ends(p):
                            if q.block == b.id:
                                continue
                            w = (
                                1
                                if f"{n['id']}|{q.id}" in self.feedback
                                or f"{n['id']}|{p.id}" in self.feedback
                                else 4
                            )
                            if q.block and self.blocks[q.block].band != b.band:
                                w = 0
                            vals += [self.py(q) - (p.off if p.side in "LR" else 0)] * w
                    want[b.id] = _med(vals) if vals else b.y
                self.pack(bs, want)
            self.place_boundary()
        self.layout_lanes()
        self.layout_ports()

    def place_boundary(self):
        """Boundary ports sit at the median height of what they connect to, packed per side."""
        for side in (self.bound_in, self.bound_out):
            want = {p.id: _med([self.py(q) for q, _ in self.other_ends(p)] or [40.0]) for p in side}
            lo = 30.0
            for p in sorted(side, key=lambda p: (want[p.id], p.id)):
                self.bound_y[p.id] = max(want[p.id], lo)
                lo = self.bound_y[p.id] + 14

    def bx(self, b) -> float:
        return b.x if b.bar and b.x is not None else self.colx[b.col]

    def mark_bars(self):
        """R14 (figure check: CV32E40P controller, Ibex register file): a control unit, or a
        memory read and written from different stages, that talks to three or more columns
        becomes a thin bar across those columns in the band above the datapath."""
        for b in self.blocks.values():
            cols = {b.col}
            for p in b.ports:
                for q, _ in self.other_ends(p):
                    if q.block and q.block != b.id and self.blocks[q.block].kind != "pipeline_reg":
                        cols.add(self.blocks[q.block].col)
            if len(cols) >= 3 and (b.band == 0 or b.kind == "memory"):
                b.bar, b.band = True, 0
                b.span = (min(cols), max(cols))
                b.h = min(b.h, 34.0 + 0 * len(b.ports))
        bars = sorted((b for b in self.blocks.values() if b.bar), key=lambda b: b.span)
        y = 30.0
        for b in bars:
            b.y = y
            y += b.h + 14
        self.bars_bottom = y

    def pack(self, bs, want):
        """Order-preserving packing: sort by wanted y, push down to clear, then pull up."""
        bs = [b for b in bs if not b.bar]
        bands = {0: [b for b in bs if b.band == 0], 1: [b for b in bs if b.band == 1]}
        floor = self.ctrl_floor()
        for band, group in bands.items():
            group.sort(key=lambda b: want[b.id])
            _sibling_order(group)
            lo = getattr(self, "bars_bottom", 30.0) if band == 0 else floor
            ys = []
            for b in group:
                y = max(want[b.id], lo)
                ys.append(y)
                lo = y + b.h + VGAP
            for b, y in zip(group, ys, strict=True):
                b.y = y

    def ctrl_floor(self) -> float:
        ctrl = [b for b in self.blocks.values() if b.band == 0 or b.bar]
        return (max(b.y + b.h for b in ctrl) + 48) if ctrl else 40.0

    def layout_lanes(self):
        """Pipeline register lanes: y = where the value comes from (straight in), packed."""
        floor = self.ctrl_floor()
        for b in self.blocks.values():
            if b.kind != "pipeline_reg":
                continue
            lanes = defaultdict(list)
            for p in b.ports:
                if p.lane:
                    lanes[p.lane].append(p)
            want = {}
            for k, ps in lanes.items():
                src = [self.py(q) for p in ps if p.dir == "input" for q, _ in self.other_ends(p)]
                dst = [self.py(q) for p in ps if p.dir == "output" for q, _ in self.other_ends(p)]
                want[k] = _med(src) if src else _med(dst or [floor])
            order = sorted(lanes, key=lambda k: want[k])
            lo, ys = -1e9, {}
            for k in order:
                ys[k] = max(want[k], lo)
                lo = ys[k] + PITCH
            top = min(ys.values()) - 14 if ys else floor
            top = min(top, floor - 6)  # bars span the control band too
            b.y = min(top, 24.0)
            for k, ps in lanes.items():
                for p in ps:
                    p.off = ys[k] - b.y
            bottom = max(ys.values()) + 14 if ys else b.y + 40
            b.h = bottom - b.y
            for p in b.ports:
                if p.side == "T":
                    p.off = b.w / 2
        bars = [b for b in self.blocks.values() if b.kind == "pipeline_reg"]
        if bars:  # R2: every pipeline register spans the same height
            top = min(b.y for b in bars)
            bot = max(b.y + b.h for b in bars)
            for b in bars:
                for p in b.ports:
                    if p.side in "LR":
                        p.off += b.y - top
                b.y, b.h = top, bot - top

    # ------------------------------------------------------------------ 4. routing (R7)
    def route(self):
        self.extent()
        cols = self.cols
        ncol = len(cols)
        self.plans = []  # per net: list of polyline specs, symbolic x
        chan_iv = {"top": [], "bot": []}
        gap_iv = defaultdict(list)  # gap index g (between col g-1 and g; g=ncol right edge)
        for n in self.nets:
            s = self.ports[n["source"]]
            scol = self.blocks[s.block].col if s.block else -1
            fwd, back = [], []
            for t in n["targets"]:
                tp = self.ports[t]
                tcol = self.blocks[tp.block].col if tp.block else ncol
                if tcol > scol:
                    fwd.append((tp, tcol))
                else:
                    ch = "top" if (tp.side == "T" or self.blocks[tp.block].band == 0) else "bot"
                    back.append((tp, tcol, ch))
            plan = {"net": n, "src": s, "fwd": [], "back": back, "trunks": {}, "chan": {}}
            sy = self.py(s)
            # forward: one vertical trunk per target gap
            for g in sorted({tc for _, tc in fwd}):
                ys = [self._entry_y(tp) for tp, tc in fwd if tc == g]
                cy = self.corridor(scol, g, sy, n["id"])
                if cy is None:  # no clear corridor (e.g. a pipeline bar in between): R7 channel
                    ch = "top" if sy < (self.top_y + self.bot_y) / 2 else "bot"
                    back += [(tp, tc, ch) for tp, tc in fwd if tc == g]
                    continue
                if cy != sy:
                    plan.setdefault("corr", {})[g] = cy
                    gap_iv[scol + 1].append(
                        (n["id"], min(sy, cy), max(sy, cy), f"c{g}", [sy], [cy])
                    )
                y0 = cy
                gap_iv[g].append((n["id"], min([y0, *ys]), max([y0, *ys]), f"t{g}", [y0], ys))
                plan["trunks"][g] = (y0, ys)
                plan["fwd"] += [(tp, tc) for tp, tc in fwd if tc == g]
            for ch in ("top", "bot"):
                group = [(tp, tc) for tp, tc, c in back if c == ch]
                if not group:
                    continue
                cy = self.top_y if ch == "top" else self.bot_y
                xs = [scol + 1] + [tc for _, tc in group]
                chan_iv[ch].append((n["id"], min(xs), max(xs), ch))
                gap_iv[scol + 1].append((n["id"], min(sy, cy), max(sy, cy), f"s{ch}", [sy], []))
                for tp, tc in group:
                    ey = self._entry_y(tp)
                    gap_iv[tc].append((n["id"], min(cy, ey), max(cy, ey), f"b{ch}{tc}", [], [ey]))
                plan["chan"][ch] = group
            self.plans.append(plan)
        # tracks
        self.ctrack = {ch: _colour([(*v, [], []) for v in iv]) for ch, iv in chan_iv.items()}
        self.gtrack = {g: _colour(iv) for g, iv in gap_iv.items()}
        ntop = 1 + max(self.ctrack["top"].values(), default=-1)
        nbot = 1 + max(self.ctrack["bot"].values(), default=-1)
        self.top_base = self.top_y - (ntop - 1) * TRACK
        self.bot_base = self.bot_y
        # x positions: gap g sits before column g
        self.gapw = {
            g: max(GAP_MIN, (1 + max(t.values(), default=0) + 1) * TRACK + 16)
            for g, t in self.gtrack.items()
        }
        lw = max([len(p.name) for p in self.bound_in], default=0)
        x = max(40.0, lw * 5.6 + 24)
        self.in_x = x - 4
        self.colx, self.gapx = [], {}
        for c in range(ncol + 1):
            self.gapx[c] = x
            x += self.gapw.get(c, GAP_MIN)
            if c < ncol:
                self.colx.append(x)
                x += max(
                    [b.w for b in self.blocks.values() if b.col == c and not b.bar], default=20
                )
        self.out_x = x
        for b in self.blocks.values():
            if b.bar:
                c0, c1 = b.span
                w1 = max(
                    [o.w for o in self.blocks.values() if o.col == c1 and not o.bar], default=20
                )
                b.x = self.colx[c0]
                b.w = self.colx[c1] + w1 - b.x
        rw = max([len(p.name) for p in self.bound_out], default=0)
        self.width = x + max(40.0, rw * 5.6 + 24)
        self.height = self.bot_y + nbot * TRACK + 40
        # shift everything down so the top channel fits
        dy = max(0.0, 46 - self.top_base)
        if dy:
            for b in self.blocks.values():
                b.y += dy
            self.bars_bottom = getattr(self, "bars_bottom", 30.0) + dy
            self.top_y += dy
            self.top_base += dy
            self.bot_y += dy
            self.bot_base += dy
            self.height += dy
            self.bound_y = {k: v + dy for k, v in self.bound_y.items()}
            for p in self.plans:
                p["trunks"] = {
                    g: (y0 + dy, [y + dy for y in ys]) for g, (y0, ys) in p["trunks"].items()
                }
                if "corr" in p:
                    p["corr"] = {g: y + dy for g, y in p["corr"].items()}

    def _entry_y(self, tp: P) -> float:
        if tp.block is None:
            return self.bound_y.get(tp.id, 0.0)
        b = self.blocks[tp.block]
        if tp.side == "T":
            return b.y - 8 - 6 * self._tidx(tp)
        return b.y + tp.off

    def _tidx(self, tp: P) -> int:
        tops = [p for p in self.blocks[tp.block].ports if p.side == "T"]
        return tops.index(tp)

    def extent(self):
        ys = [b.y for b in self.blocks.values()] + [b.y + b.h for b in self.blocks.values()]
        self.top_y = min(ys) - 22
        self.bot_y = max(ys) + 26

    def corridor(self, scol: int, tcol: int, y: float, nid: str) -> float:
        """A y clear of blocks in the columns strictly between scol and tcol, and of other
        nets' corridors over the same columns (no shared horizontals)."""
        mids = [b for b in self.blocks.values() if scol < b.col < tcol]
        if not mids:
            return y
        used = getattr(self, "corr_used", None)
        if used is None:
            used = self.corr_used = []

        ends = [b for b in self.blocks.values() if scol <= b.col <= tcol]
        port_ys = [
            b.y + p.off
            for b in ends
            for p in b.ports
            if p.side in "LR" and all(n["id"] != nid for n in p.nets)
        ]

        def clear(yy):
            if any(b.y - 5 <= yy <= b.y + b.h + 5 for b in mids):
                return False
            if any(abs(yy - py) < 3 for py in port_ys):
                return False
            return all(
                n == nid or abs(yy - u) >= TRACK - 0.5 or hi <= scol or lo >= tcol
                for u, lo, hi, n in used
            )

        if clear(y):
            used.append((y, scol, tcol, nid))
            return y  # straight through
        base = sorted(
            {b.y - 12 for b in mids} | {b.y + b.h + 12 for b in mids}, key=lambda v: abs(v - y)
        )
        cands = [c + sgn * k * TRACK for c in base for k in range(6) for sgn in (1, -1)]
        c = next((c for c in cands if clear(c)), None)
        if c is not None:
            used.append((c, scol, tcol, nid))
        return c

    def gx(self, g: int, nid: str, tag: str) -> float:
        k = self.gtrack[g][(nid, tag)]
        return self.gapx[g] + 10 + k * TRACK

    def cy(self, ch: str, nid: str) -> float:
        k = self.ctrack[ch][(nid, ch)]
        return self.top_y - k * TRACK if ch == "top" else self.bot_y + k * TRACK

    # ------------------------------------------------------------------ 5. render
    def svg(self, title: str = "") -> str:
        out = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:.0f}" '
            f'height="{self.height:.0f}" viewBox="0 0 {self.width:.0f} {self.height:.0f}" '
            'font-family="Helvetica, Arial, sans-serif">',
            '<defs><marker id="ar" viewBox="0 0 8 8" refX="7.5" refY="4" markerWidth="6" '
            'markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#000"/></marker>'
            "</defs>",
            '<rect width="100%" height="100%" fill="#fff"/>',
        ]
        self.segs = []
        wires, dots = [], []
        for plan in self.plans:
            n, s = plan["net"], plan["src"]
            nid = n["id"]
            sx, sy = self.pxy(s)
            ctrl = n["class"] == "control"
            style = (
                'stroke="#000" stroke-width="0.9" stroke-dasharray="4 2.5"'
                if ctrl
                else f'stroke="#000" stroke-width="{1.5 if n["width"] > 1 else 1.0}"'
            )
            paths = []
            scol = self.blocks[s.block].col if s.block else -1
            for g, (y0, _ys) in plan["trunks"].items():
                x = self.gx(g, nid, f"t{g}")
                if "corr" in plan and g in plan["corr"]:
                    xc = self.gx(scol + 1, nid, f"c{g}")
                    paths.append([(sx, sy), (xc, sy), (xc, y0), (x, y0)])
                else:
                    paths.append([(sx, sy), (x, sy)])
                for tp, tc in plan["fwd"]:
                    if tc != g:
                        continue
                    paths.append(self._tail((x, y0), tp))
                if len([1 for _, tc in plan["fwd"] if tc == g]) > 1 or len(plan["trunks"]) > 1:
                    dots.append((x, y0))
            for ch, group in plan["chan"].items():
                xs = self.gx(scol + 1, nid, f"s{ch}")
                cyy = self.cy(ch, nid)
                paths.append([(sx, sy), (xs, sy), (xs, cyy)])
                for tp, tc in group:
                    xt = self.gx(tc, nid, f"b{ch}{tc}")
                    paths.append([(xs, cyy), (xt, cyy)] + self._tail((xt, cyy), tp)[1:])
                if len(group) > 1 or plan["trunks"]:
                    dots.append((xs, sy) if plan["trunks"] else (xs, cyy))
            for pts in paths:
                pts = _simplify(pts)
                if len(pts) < 2:
                    continue
                d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
                end = pts[-1]
                is_sink = any(
                    math.dist(end, self.pxy(tp)) < 0.5
                    for tp in [self.ports[t] for t in n["targets"]]
                )
                mk = ' marker-end="url(#ar)"' if is_sink else ""
                wires.append(
                    f'<path data-rtl2d-kind="wire" data-rtl2d-id="{nid}" d="{d}" '
                    f'fill="none" {style}{mk}/>'
                )
                self.segs += [(nid, a, b) for a, b in zip(pts, pts[1:], strict=False)]
            skind = self.blocks[s.block].kind if s.block else ""
            if (
                n["width"] > 1
                and n["width"] != self.main_w
                and not ctrl
                and skind not in ("pipeline_reg", "split")
            ):  # R9
                x1 = sx + 8
                wires.append(
                    f'<path d="M{x1 - 3:.1f},{sy + 4:.1f} L{x1 + 3:.1f},{sy - 4:.1f}" '
                    'stroke="#000" stroke-width="0.8"/>'
                )
                wires.append(
                    f'<text x="{x1 + 1:.1f}" y="{sy - 5:.1f}" font-size="7">{n["width"]}</text>'
                )
        # stage titles + guide lines (R1, R10)
        names = self.stage_names()
        for s in range(self.nstage if (names or self.nstage > 1) else 0):
            cs = [i for i, c in enumerate(self.cols) if c[0] == "st" and c[1] == s]
            if not cs:
                continue
            x0 = self.gapx[cs[0]]
            nxt = cs[-1] + 1
            x1 = (
                self.gapx.get(nxt, self.width - 80) + self.gapw.get(nxt, GAP_MIN)
                if nxt < len(self.cols) and self.cols[nxt][0] == "st"
                else self.colx[cs[-1]]
                + max([b.w for b in self.blocks.values() if b.col == cs[-1]], default=20)
                + self.gapw.get(nxt, GAP_MIN)
            )
            out.append(
                f'<text x="{(x0 + x1) / 2:.1f}" y="18" font-size="13" font-weight="bold" '
                f'text-anchor="middle">{names.get(s, f"S{s}")}</text>'
            )
        out += wires
        for b in self.blocks.values():
            x0 = self.bx(b)
            out.append(
                f'<g data-rtl2d-kind="block" data-rtl2d-id="{b.id}" '
                f'data-rtl2d-bbox="{x0:.1f} {b.y:.1f} {b.w:.1f} {b.h:.1f}">'
            )
            out.append(self.shape(b))
            out.append("</g>")
        for x, y in dots:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.2" fill="#000"/>')
        for p in self.bound_out:
            x, y = self.pxy(p)
            out.append(f'<text x="{x + 4:.1f}" y="{y + 3:.1f}" font-size="9">{p.name}</text>')
        for p in self.bound_in:
            x, y = self.pxy(p)
            out.append(
                f'<path d="M{x - 6:.1f},{y - 3.5:.1f} L{x:.1f},{y:.1f} '
                f'L{x - 6:.1f},{y + 3.5:.1f} z" fill="#fff" stroke="#000"/>'
            )
            out.append(
                f'<text x="{x - 9:.1f}" y="{y + 3:.1f}" font-size="9" '
                f'text-anchor="end">{p.name}</text>'
            )
        if title:
            out.append(
                f'<text x="8" y="{self.height - 8:.0f}" font-size="9" fill="#555">{title}</text>'
            )
        out.append("</svg>")
        return "\n".join(out)

    def _tail(self, a, tp: P):
        tx, ty = self.pxy(tp)
        x, y = a
        if tp.side == "T":
            ey = self._entry_y(tp)
            return [(x, y), (x, ey), (tx, ey), (tx, ty)]
        return [(x, y), (x, ty), (tx, ty)]

    def stage_names(self) -> dict:
        names = {}
        for g in self.meta.get("teacher_groups", []):
            m = re.match(r"\s*([A-Za-z]+)", g["name"])
            if g.get("kind") != "PIPELINE_STAGE" or not m:
                continue
            ss = [
                self.blocks[i].hint.get("stage_index") for i in g["instances"] if i in self.blocks
            ]
            ss = [s for s in ss if s is not None]
            if ss:
                names.setdefault(max(set(ss), key=ss.count), m.group(1).upper())
        return names

    def shape(self, b: B) -> str:
        x, y, w, h = self.bx(b), b.y, b.w, b.h
        lab = nice(b.label, b.kind)
        if b.kind == "mux" and any(o.label == lab for o in self.blocks.values()):
            lab = b.label  # 'PC' alone would read as the PC register
        g = []
        line = 'fill="#fff" stroke="#000" stroke-width="1.3"'
        cx, cy = x + w / 2, y + h / 2
        if b.kind == "mux":  # R4
            g.append(
                f'<path d="M{x},{y} L{x + w},{y + 9} L{x + w},{y + h - 9} L{x},{y + h} z" {line}/>'
            )
            for i, p in enumerate(
                sorted([p for p in b.ports if p.side == "L"], key=lambda p: p.name)
            ):
                g.append(f'<text x="{x + 3}" y="{y + p.off + 3:.1f}" font-size="7">{i}</text>')
            g.append(
                f'<text x="{cx:.1f}" y="{y + h + 10:.1f}" font-size="7.5" '
                f'text-anchor="middle">{lab}</text>'
            )
        elif b.kind in ("alu", "adder"):  # R5
            n = h * 0.18
            g.append(
                f'<path d="M{x},{y} L{x + w},{y + h * 0.25} L{x + w},{y + h * 0.75} '
                f'L{x},{y + h} L{x},{cy + n} L{x + n},{cy} L{x},{cy - n} z" {line}/>'
            )
            g.append(
                f'<text x="{cx + 4:.1f}" y="{cy + 3.5:.1f}" font-size="9" '
                f'font-weight="bold" text-anchor="middle">{lab}</text>'
            )
        elif b.kind == "pipeline_reg":  # R2
            g.append(
                f'<rect x="{x}" y="{y:.1f}" width="{w}" height="{h:.1f}" fill="#eee" '
                'stroke="#000" stroke-width="1.3"/>'
            )
            g.append(
                f'<text x="{cx:.1f}" y="{y + h + 12:.1f}" font-size="9" font-weight="bold" '
                f'text-anchor="middle">{lab}</text>'
            )
            for p in b.ports:
                if p.dir == "output":
                    g.append(
                        f'<text x="{x + w + 3:.1f}" y="{y + p.off - 2.5:.1f}" '
                        f'font-size="6.5" fill="#333">{p.name}</text>'
                    )
        elif b.kind == "split":
            g.append(f'<rect x="{x}" y="{y:.1f}" width="{w}" height="{h:.1f}" fill="#000"/>')
            for p in b.ports:
                if p.dir == "output":
                    g.append(
                        f'<text x="{x + w + 3:.1f}" y="{y + p.off - 2.5:.1f}" '
                        f'font-size="7">{p.name.removeprefix("id_")}</text>'
                    )
        else:  # R3: rectangles; control rounded
            rx = 10 if b.kind == "control" else 1.5
            g.append(f'<rect x="{x}" y="{y:.1f}" width="{w}" height="{h:.1f}" rx="{rx}" {line}/>')
            fs = 10 if b.kind == "memory" else 9
            g.append(
                f'<text x="{cx:.1f}" y="{y + 13:.1f}" font-size="{fs}" font-weight="bold" '
                f'text-anchor="middle">{lab}</text>'
            )
            if b.kind == "register":
                g.append(
                    f'<path d="M{cx - 5:.1f},{y + h} L{cx:.1f},{y + h - 6} '
                    f'L{cx + 5:.1f},{y + h}" fill="none" stroke="#000"/>'
                )
            if b.kind in ("memory", "comb", "control"):
                for p in b.ports:
                    if p.side == "L":
                        g.append(
                            f'<text x="{x + 3}" y="{y + p.off + 2.5:.1f}" '
                            f'font-size="6.5">{p.name}</text>'
                        )
                    elif p.side == "R":
                        g.append(
                            f'<text x="{x + w - 3}" y="{y + p.off + 2.5:.1f}" '
                            f'font-size="6.5" text-anchor="end">{p.name}</text>'
                        )
        return "\n".join(g)

    # ------------------------------------------------------------------ metrics
    def metrics(self) -> dict:
        hs = [(n, a, b) for n, a, b in self.segs if abs(a[1] - b[1]) < 0.01 and a != b]
        vs = [(n, a, b) for n, a, b in self.segs if abs(a[0] - b[0]) < 0.01 and a != b]
        cross = 0
        for n1, a, b in hs:
            x0, x1, y = min(a[0], b[0]), max(a[0], b[0]), a[1]
            for n2, c, d in vs:
                if n1 == n2:
                    continue
                y0, y1, x = min(c[1], d[1]), max(c[1], d[1]), c[0]
                if x0 + 0.5 < x < x1 - 0.5 and y0 + 0.5 < y < y1 - 0.5:
                    cross += 1
        bends = sum(1 for _ in self.segs) - len(self.plans)
        length = sum(math.dist(a, b) for _, a, b in self.segs)
        return {
            "cross": cross,
            "segments": len(self.segs),
            "bends~": bends,
            "length": round(length),
            "size": [round(self.width), round(self.height)],
        }


def _stem(label: str) -> str:
    return re.sub(r"\s*\b([A-D]|[0-9])\b", "", label).strip()


def _sibling_order(group: list) -> None:
    """Siblings (same kind, labels equal up to an A/B or 1/2 token: 'FWD A MUX', 'FWD B MUX')
    keep reading order top to bottom, in the slots the packing gave them."""
    by = defaultdict(list)
    for i, b in enumerate(group):
        by[(b.kind, _stem(b.label))].append(i)
    for idx in by.values():
        if len(idx) > 1:
            sib = sorted((group[i] for i in idx), key=lambda b: b.label)
            for i, b in zip(idx, sib, strict=True):
                group[i] = b


def apply_view(diagram: dict, meta: dict, view: str) -> dict:
    """'full': everything. 'datapath': drop the blocks of the teacher's CONTROLLER groups
    (L1 annotation), like the basic pipelined-datapath figure that omits hazard control."""
    if view == "full":
        return diagram
    hide = {
        i
        for g in meta.get("teacher_groups", [])
        if g["kind"] == "CONTROLLER"
        for i in g["instances"]
    }
    owner = {p["id"]: p["owner_block_id"] for p in diagram["ports"]}
    nets = []
    for n in diagram["nets"]:
        if owner[n["source"]] in hide:
            continue
        ts = [t for t in n["targets"] if owner[t] not in hide]
        if ts:
            nets.append({**n, "targets": ts})
    return {
        **diagram,
        "blocks": [b for b in diagram["blocks"] if b["id"] not in hide],
        "ports": [p for p in diagram["ports"] if p["owner_block_id"] not in hide],
        "nets": nets,
    }


def bundle(diagram: dict, kinds: dict, meta: dict | None = None, min_n: int = 3) -> dict:
    """R12: three or more connections between the same two ends become one bundle wire.
    An end is a block, or a teacher interface (a named group of boundary ports, e.g. an AXI
    channel). Data lanes into pipeline registers and bus-field taps stay separate (R2).
    Presentation only: the members are kept in the bundle net's `members`."""
    ports = {p["id"]: dict(p) for p in diagram["ports"]}
    itf_of = {pid: i["name"] for i in (meta or {}).get("interfaces", []) for pid in i["ports"]}

    def end(pid):
        o = ports[pid]["owner_block_id"]
        if o:
            return o
        return f"itf:{itf_of[pid]}" if pid in itf_of else None

    pairs = defaultdict(list)
    for n in diagram["nets"]:
        if n["class"] in ("clock", "reset"):
            continue
        S = end(n["source"])
        for t in n["targets"]:
            D = end(t)
            if S is None or D is None or S == D:
                continue
            if kinds.get(D) == "pipeline_reg" and n["class"] != "control":
                continue
            if "split" in (kinds.get(S), kinds.get(D)):
                continue
            pairs[(S, D)].append((n, t))
    cut = defaultdict(set)  # net id -> targets moved into a bundle
    new_n = []
    for (S, D), lst in pairs.items():
        if len(lst) < min_n:
            continue
        members = {n["id"]: n for n, _ in lst}
        w = sum(n["width"] for n in members.values())
        cls = "data" if any(n["class"] == "data" for n in members.values()) else "control"
        name = "ctrl" if cls == "control" else f"{len(members)} sig"
        if S.startswith("itf:") or D.startswith("itf:"):
            name = (S if S.startswith("itf:") else D)[4:]
        sp = f"{S}.bus__to__{D}" if not S.startswith("itf:") else f"itf.{S[4:]}.to.{D}"
        tp = f"{D}.bus__from__{S}" if not D.startswith("itf:") else f"itf.{D[4:]}.from.{S}"
        sp, tp = (re.sub(r"[^A-Za-z0-9_.\-]", "_", x) for x in (sp, tp))
        ports[sp] = {
            "id": sp,
            "owner_block_id": None if S.startswith("itf:") else S,
            "direction": "input" if S.startswith("itf:") else "output",
            "width": w,
            "class": cls,
            "name": name,
            "bundle": True,
        }
        ports[tp] = {
            "id": tp,
            "owner_block_id": None if D.startswith("itf:") else D,
            "direction": "output" if D.startswith("itf:") else "input",
            "width": w,
            "class": cls,
            "name": name,
            "bundle": True,
        }
        for n, t in lst:
            cut[n["id"]].add(t)
        new_n.append(
            {
                "id": f"n.{sp}",
                "source": sp,
                "targets": [tp],
                "width": w,
                "class": cls,
                "members": sorted(members),
            }
        )
    nets = []
    for n in diagram["nets"]:
        ts = [t for t in n["targets"] if t not in cut.get(n["id"], ())]
        if ts:
            nets.append({**n, "targets": ts})
    return {**diagram, "ports": list(ports.values()), "nets": nets + new_n}


def _med(v):
    v = sorted(v)
    if not v:
        return 0.0
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def _colour(iv):
    """Track assignment in a gap or channel. iv: (net, lo, hi, tag, stub_ys, tail_ys); one
    track per (net, tag). A stub (horizontal leaving the left column at y) must sit left of
    any other net's tail (horizontal entering the right column) at the same y, or the two
    horizontals overlap; those pairs become ordering constraints."""
    merged, stubs, tails = {}, defaultdict(list), defaultdict(list)
    for nid, lo, hi, tag, st, tl in iv:
        k = (nid, tag)
        a, b = merged.get(k, (lo, hi))
        merged[k] = (min(a, lo), max(b, hi))
        stubs[k] += st
        tails[k] += tl
    after = defaultdict(set)  # k -> keys that must be left of k
    for a in merged:
        for b in merged:
            if a[0] != b[0] and any(abs(y1 - y2) < 1 for y1 in stubs[a] for y2 in tails[b]):
                after[b].add(a)
    res: dict = {}
    tracks: list[list] = []
    todo = sorted(merged, key=lambda k: (merged[k][1] - merged[k][0], merged[k][0]))
    while todo:
        ready = [k for k in todo if all(a in res or a not in todo for a in after[k])] or todo[:1]
        k = ready[0]
        todo.remove(k)
        lo, hi = merged[k]
        first = 1 + max((res[a] for a in after[k] if a in res), default=-1)
        for i in range(first, len(tracks) + 1):
            if i == len(tracks):
                tracks.append([])
            if all(hi + 4 < a or lo - 4 > b for a, b in tracks[i]):
                tracks[i].append((lo, hi))
                res[k] = i
                break
    return res


def _simplify(pts):
    out = []
    for p in pts:
        if out and math.dist(out[-1], p) < 0.01:
            continue
        if len(out) >= 2:
            (x0, y0), (x1, y1) = out[-2], out[-1]
            if (abs(x0 - x1) < 0.01 and abs(x1 - p[0]) < 0.01) or (
                abs(y0 - y1) < 0.01 and abs(y1 - p[1]) < 0.01
            ):
                out[-1] = p
                continue
        out.append(p)
    return out


def render(
    diagram: dict, hints: dict, meta: dict, title: str = "", view: str = "full", bars: bool = False
) -> tuple[str, dict]:
    """bars=True draws control units / cross-stage memories as top-spanning bars (R14). Off by
    default: with side ports the bars pull wires through themselves (CPU: through 0 -> 70)."""
    d = Drawing(apply_view(diagram, meta, view), hints, meta)
    d.bars = bars
    d.columns()
    d.sides()
    d.place()
    d.route()
    svg = d.svg(title)
    return svg, d.metrics()


def main(stem: str, views: list[str]) -> None:
    base = Path(stem)
    load = lambda suf: json.loads(Path(f"{stem}.{suf}.json").read_text())  # noqa: E731
    for view in views or ["full"]:
        svg, m = render(
            load("diagram"), load("hints"), load("meta"), title=f"{base.name} ({view})", view=view
        )
        Path(f"{stem}.paper-{view}.svg").write_text(svg, encoding="utf-8")
        print(base.name, view, m)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
