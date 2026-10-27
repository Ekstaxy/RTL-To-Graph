"""TimingDiagram v0.1 (as a dict) -> WaveDrom JSON -> SVG with data-rtl2d tags.

    uv run --package rtl2d-l3 python layers/l3_draw/experiments/e4_fsm_timing_draw/wave_draw.py \
        TIMING.json OUT_STEM --node runs/.tools/x3/node/bin/node \
        --cli runs/.tools/wavedrom/node_modules/wavedrom-cli/wavedrom-cli.js

Writes OUT_STEM.wavedrom.json (the WaveDrom source plus an "rtl2d" key with the column map
wave_check reads back) and OUT_STEM.svg.

Grid (README "Time grid"): every drawn wave character is one posedge-to-posedge cycle of its
lane's domain. All lanes share one WaveDrom base unit of `u` simulation time units,
u = gcd(all periods, 2 x every lane's start offset), so a domain of period P is drawn with the
per-signal WaveDrom `period` P/u and `phase` offset/u x hscale (WaveDrom phase moves a lane
left in half-unit bricks). Sampling convention (x4 vcd.py / timing_bridge): the sample of
cycle c is the value just before posedge c, i.e. the value held during [posedge c-1, posedge c).
It is drawn in the column that ENDS at posedge c, so a register changes exactly at the edge
that loads it and a testbench input changes where the VCD changes it (within the cycle).
A single-domain diagram therefore has u = period: one character per cycle.

Gaps: the hidden cycles of a Gap are never drawn as values. In every domain that keeps any
hidden column, the first one is hatched ('x', not sampled) and the second carries the '|' gap
glyph (still hatched). Time removed: in a multi-domain diagram it must be the same for every
domain and a whole number of cycles in each, so it is k x lcm(periods) with the largest k that
leaves 2 hidden columns (hatch + glyph) in every domain, or 1 if some domain hides only one
cycle. If k = 0 the gap is drawn uncompressed and the label says so (recorded). A Gap that
hides no cycle in any domain (adjacent window breaks) gets no glyph and no label, only an empty
tagged <g> so the round trip finds it (recorded). A text node '+N cyc' (multi-domain: one count
per domain) sits in a row above the lanes, over the gap glyph.

Arrows: hidden (upper-case) WaveDrom node letters at the src/dst columns; edges '~>' next
cycle, '-|>' same cycle, '-~>' cdc (re-coloured orange and dashed after rendering).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
NODE_POOL = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
             "ÀÁÂÃÄÅÆÇÈÉÊËÌ"
             "ÍÎÏÐÑÒÓÔÕÖØÙÚ"
             "ÛÜÝÞ"
             "ΑΒΓΔΕΖΗΘΙΚΛΜΝ"
             "ΞΟΠΡΣΤΥΦΧΨΩ")
HIDDEN = "\x00hidden"  # lane_wave state inside a gap (never equal to a sample value)
UNIT_PX = {"default": 40, "narrow": 20}  # px per WaveDrom base unit at hscale 1
CHAR_PX = 7.6  # estimated px per character of an 11pt Helvetica data label
LABEL_PAD = 12  # px of air around a data label (segment ends are slanted)
MAX_HSCALE = 3
FAST_CYCLE_PX = 48  # multi-domain: drawn width of one fastest-domain cycle
EDGE = {"next": "~>", "same": "-|>", "cdc": "-~>"}
C_CDC = "#d35400"
SAMPLING_NOTE = "  ·  value = sample just before a posedge, drawn in the cycle ending there"


def _sibling(name: str):
    key = f"e4_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- columns


@dataclass
class Col:
    kind: str  # "pad" (before the first sample) | "s" (a drawn sample) | "hold" (in a gap)
    cycle: int | None = None
    t: int | None = None
    gap: str | None = None
    mark: bool = False  # carries the '|' glyph


@dataclass
class GapPlan:
    id: str
    after_t: int
    until_t: int
    declared: dict[str, int]
    hidden: dict[str, int] = field(default_factory=dict)  # domain id -> hidden posedges
    removed: int = 0  # simulation time removed from the drawing (k x lcm)
    implicit: bool = False


def domain_cycles(dm: dict) -> list[tuple[int, int]]:
    """Sorted (cycle, t) drawn in this domain (union over its lanes)."""
    cyc: dict[int, int] = {}
    for ln in dm["lanes"]:
        for s in ln["values"]:
            cyc.setdefault(s["cycle"], s["t"])
    return sorted(cyc.items())


def plan_gaps(d: dict, cycles: dict[str, list[tuple[int, int]]], notes: list[dict]) -> list:
    """Declared gaps plus implicit ones (holes in a domain's cycles that no Gap covers)."""
    plans = [GapPlan(f"g.{i}", g["after_t"], g["until_t"], dict(g.get("cycles") or {}))
             for i, g in enumerate(d.get("gaps") or [])]
    n_imp = 0
    for did, cs in cycles.items():
        for (ca, ta), (cb, tb) in zip(cs, cs[1:], strict=False):
            if cb == ca + 1 or any(ta <= p.after_t < p.until_t <= tb for p in plans):
                continue
            n_imp += 1
            plans.append(GapPlan(f"g.implicit.{n_imp}", ta, tb, {}, implicit=True))
            notes.append({"what": f"{did} cycles {ca + 1}..{cb - 1} are not drawn and no Gap "
                          "declares them; drawn as an undeclared gap",
                          "reason": "TimingDiagram lane values skip cycles without a Gap"})
    plans.sort(key=lambda p: (p.after_t, p.until_t))
    for p in plans:
        for did, cs in cycles.items():
            pre = [c for c, t in cs if t <= p.after_t]
            post = [c for c, t in cs if t >= p.until_t]
            inside = [c for c, t in cs if p.after_t < t < p.until_t]
            if inside:
                notes.append({"what": f"{p.id}: {did} has drawn cycles {inside[:5]} inside the "
                              "gap", "reason": "Gap overlaps drawn samples; counts taken from "
                              "the samples around it"})
            if pre and post:
                p.hidden[did] = post[0] - pre[-1] - 1
                if did in p.declared and p.declared[did] != p.hidden[did]:
                    notes.append({"what": f"{p.id}: {did} declares {p.declared[did]} hidden "
                                  f"cycles, the samples imply {p.hidden[did]}",
                                  "reason": "drawn from the samples; Gap.cycles disagrees"})
    return plans


def compress(plans: list[GapPlan], periods: dict[str, int], notes: list[dict]) -> None:
    """Choose the removed time of every gap: k x lcm(periods of the spanning domains)."""
    for p in plans:
        spans = {did: n for did, n in p.hidden.items()}
        if not spans:
            continue
        lcm = math.lcm(*(periods[did] for did in spans))
        lo = min(spans.values())
        keep = 2 if lo >= 2 else 1
        k = 0 if lo < 1 else min((n - keep) * periods[did] // lcm for did, n in spans.items())
        p.removed = k * lcm
        if max(spans.values()) == 0:
            continue
        left = {did: n - p.removed // periods[did] for did, n in spans.items()}
        if k == 0:
            why = (f"only {lo} hidden cycle(s): all drawn in place, hatched" if len(spans) == 1
                   else f"removing a whole common period (lcm={lcm}) would leave a domain "
                   "without a hatched column; removing less would shift the domains' "
                   "relative phase")
            notes.append({"what": f"{p.id} drawn uncompressed ({spans} hidden cycles)",
                          "reason": why})
        notes.append({"what": f"{p.id}: hidden cycles kept as hatched columns {left}",
                      "reason": "a gap is shown as a hatched column plus a '|' glyph column; "
                      "hidden cycles are not sampled, so no value is drawn there"})


def ctime(t: int, plans: list[GapPlan], t0: int) -> int:
    """Compressed drawing time of simulation time t."""
    return t - t0 - sum(p.removed for p in plans if p.until_t <= t)


def col_start(t: int, period: int, plans: list[GapPlan], t0: int) -> int:
    """Compressed drawing time where the column of the sample at posedge t starts (the column
    ends at that posedge: the sample is the value held during the cycle before it)."""
    return ctime(t, plans, t0) - period


def build_cols(cs: list[tuple[int, int]], period: int, plans: list[GapPlan], t0: int) -> tuple:
    """Columns of one domain and its start offset (compressed time of its first column, <= 0)."""
    c_first = col_start(cs[0][1], period, plans, t0)
    pad = -(-c_first // period)
    cols = [Col("pad", t=cs[0][1] - (pad - i) * period) for i in range(pad)]
    for (ca, ta), (cb, _tb) in zip(cs, cs[1:] + [(None, None)], strict=False):
        cols.append(Col("s", ca, ta))
        if cb is None or cb == ca + 1:
            continue
        p = next(p for p in plans if ta <= p.after_t and p.until_t <= _tb)
        n = cb - ca - 1 - p.removed // period
        cols += [Col("hold", gap=p.id, mark=(i == 1)) for i in range(n)]
    return cols, c_first - pad * period


def _check_alignment(did, cols, off, period, plans, t0) -> None:
    """Every drawn sample must start exactly at its compressed posedge time (internal guard)."""
    for i, c in enumerate(cols):
        want = col_start(c.t, period, plans, t0) if c.kind == "s" else None
        if want is not None and i * period + off != want:
            raise RuntimeError(f"{did}: column {i} (cycle {c.cycle}, t={c.t}) would start at "
                               f"{i * period + off}, not {want}; samples are not on a period "
                               "grid")


# --------------------------------------------------------------------------- waves


def norm(v: str) -> str:
    return str(v).strip().lower()


def enum_name(v: str, enum: dict | None) -> str | None:
    if not enum:
        return None
    if v in enum:
        return enum[v]
    try:
        iv = int(v, 16)
    except ValueError:
        return None
    for k, name in enum.items():
        try:
            if int(str(k).replace("0x", ""), 16) == iv:
                return name
        except ValueError:
            continue
    return None


def lane_wave(ln: dict, cols: list[Col], notes: list[dict]) -> tuple[str, list[str]]:
    """Wave string and data labels of one lane over its domain's columns."""
    vals = {s["cycle"]: norm(s["v"]) for s in ln["values"]}
    bus = ln.get("width", 1) > 1 or bool(ln.get("enum"))
    wave, data, prev = [], [], None
    odd: dict[str, list[int]] = {"missing": [], "not01xz": [], "noname": []}
    for c in cols:
        if c.kind == "pad":
            ch, cur = ("x" if prev is None else "."), "x"
        elif c.kind == "hold":
            ch, cur = ("|" if c.mark else ("." if prev in (HIDDEN, "x") else "x")), HIDDEN
        else:
            cur = vals.get(c.cycle)
            if cur is None:
                cur = "x"
                odd["missing"].append(c.cycle)
            if cur == prev:
                ch = "."
            elif not bus:
                ch = cur if cur in ("0", "1", "x", "z") else "x"
                if ch != cur:
                    odd["not01xz"].append(c.cycle)
            elif set(cur) <= {"x"} or set(cur) <= {"z"}:
                ch = cur[0]
            else:
                ch = "="
                name = enum_name(cur, ln.get("enum"))
                if ln.get("enum") and name is None:
                    odd["noname"].append(c.cycle)
                data.append(name or cur)
        wave.append(ch)
        prev = cur
    why = {"missing": ("no sample; drawn x", "lanes of one domain sample different cycles"),
           "not01xz": ("1-bit value not 0/1/x/z; drawn x", "WaveDrom has no glyph for it"),
           "noname": ("value has no state name; drawn as hex", "value not in Lane.enum")}
    for k, cyc in odd.items():
        if cyc:
            notes.append({"what": f"{ln['id']} cycles {cyc[:8]}{'...' if len(cyc) > 8 else ''}"
                          f": {why[k][0]}", "reason": why[k][1]})
    return "".join(wave), data


def segments(wave: str) -> list[int]:
    """Length in characters of every '=' segment (the '=' plus its repeats)."""
    out: list[int] = []
    inside = False
    for ch in wave:
        if ch == "=":
            out.append(1)
            inside = True
        elif ch in ".|" and inside:
            out[-1] += 1
        else:
            inside = False
    return out


def label_px(text: str) -> float:
    return CHAR_PX * len(text) + LABEL_PAD


def _need_px(lanes: list[dict]) -> float:
    """Smallest px per base unit at which every data label fits its segment."""
    need = 0.0
    for ln in lanes:
        for t, n in zip(ln["data"], segments(ln["wave"]), strict=False):
            need = max(need, label_px(t) / (n * ln["_per"]))
    return need


def choose_scale(lanes: list[dict], skin: str, multi: bool) -> tuple[int, float]:
    """(WaveDrom hscale, horizontal squeeze sx <= 1).

    Single domain: the smallest integer hscale at which the labels fit (sx = 1).
    Multi-domain: one fastest-domain cycle is drawn FAST_CYCLE_PX wide (or wider when a label
    needs it), reached with hscale and then a horizontal squeeze of the wave area applied after
    rendering (text is not squeezed); WaveDrom's own minimum is 20 px per base unit, which makes
    a 10:14 diagram on a 2-unit grid 100 px per fast cycle."""
    unit, need = UNIT_PX[skin], _need_px(lanes)
    if not multi:
        return min(MAX_HSCALE, max(1, math.ceil(need / unit))), 1.0
    fast = min(ln["_per"] for ln in lanes)
    e = min(max(FAST_CYCLE_PX / fast, need), unit * MAX_HSCALE)
    h = max(1, math.ceil(e / unit - 1e-9))
    sx = e / (unit * h)
    return h, (1.0 if sx > 0.95 else round(sx, 4))


def fit_labels(lanes: list[dict], px_unit: float, notes: list[dict]) -> None:
    """Shorten (with a trailing ellipsis) the labels that still do not fit; one note per lane."""
    for ln in lanes:
        cut = []
        for i, (t, n) in enumerate(zip(ln["data"], segments(ln["wave"]), strict=False)):
            room = n * ln["_per"] * px_unit
            if label_px(t) > room + 0.5:
                keep = max(1, int((room - LABEL_PAD) / CHAR_PX) - 1)
                ln["data"][i] = t[:keep] + "\u2026"
                cut.append(f"{t!r}->{ln['data'][i]!r}")
        if cut:
            notes.append({"what": f"{ln['_id']}: {len(cut)} data label(s) shortened, e.g. "
                          + ", ".join(cut[:3]),
                          "reason": "segment narrower than the label at the widest allowed "
                          "scale (full values stay in the TimingDiagram JSON)"})


# --------------------------------------------------------------------------- assemble


def _gap_label(p: GapPlan, clock_of: dict[str, str]) -> str:
    counts = p.declared if p.declared else p.hidden
    if len(counts) == 1:
        txt = f"+{next(iter(counts.values()))} cyc"
    else:
        txt = " / ".join(f"+{n} {clock_of.get(did, did)}" for did, n in counts.items())
    if p.removed == 0:
        txt += " (not compressed)"
    if p.implicit:
        txt += " (undeclared)"
    return txt


def _foot(d: dict, kinds: set[str], has_gap: bool) -> tuple[str, str]:
    """(stimulus line, legend line)."""
    st = d.get("stimulus") or {}
    ver = (st.get("version") or "").split(" (")[0]
    sim = ver if st.get("simulator") and st["simulator"].lower() in ver.lower() else \
        " ".join(x for x in (st.get("simulator"), ver) if x)
    stim = f"stimulus: {st.get('kind', '?')}" + (
        f" (seed {st['seed']})" if st.get("seed") is not None else "") + (
        f", {sim}" if sim else "") + SAMPLING_NOTE
    leg = {"next": "\u219d next cycle (1 register)", "same": "\u2193 same cycle (combinational)",
           "cdc": "orange dashed: clock-domain crossing"}
    parts = [leg[k] for k in ("next", "same", "cdc") if k in kinds]
    if has_gap:
        parts.append("hatched + // : cycles hidden (not sampled), count above")
    return stim, "  \u00b7  ".join(parts)


def to_wavejson(d: dict) -> tuple[dict, list[dict]]:
    """WaveDrom source with an "rtl2d" column map; and the drawing simplifications."""
    notes: list[dict] = []
    doms = [dm for dm in d["domains"] if domain_cycles(dm)]
    for dm in d["domains"]:
        if dm not in doms:
            notes.append({"what": f"domain {dm['id']} has no drawn sample; not drawn",
                          "reason": "no lane values"})
    if not doms:
        raise RuntimeError("no drawn sample in any domain (every lane has empty values)")
    cycles = {dm["id"]: domain_cycles(dm) for dm in doms}
    periods = {dm["id"]: int(dm["period"]) for dm in doms}
    plans = plan_gaps(d, cycles, notes)
    compress(plans, periods, notes)
    t0 = min(cs[0][1] - periods[did] for did, cs in cycles.items())
    cols, offs = {}, {}
    for did, cs in cycles.items():
        cols[did], offs[did] = build_cols(cs, periods[did], plans, t0)
        _check_alignment(did, cols[did], offs[did], periods[did], plans, t0)
    u = math.gcd(*periods.values(), *(2 * -o for o in offs.values()))
    multi = len(doms) > 1
    skin = "narrow" if multi and min(periods.values()) // u >= 3 else "default"
    lanes: list[dict] = []
    for dm in doms:
        did = dm["id"]
        per = periods[did] // u
        lanes.append({"_id": f"clk.{did}", "_kind": "clock", "_dom": did, "_per": per,
                      "wave": "".join("p" if i == 0 else ("|" if c.mark else ".")
                                      for i, c in enumerate(cols[did])), "data": []})
        for ln in dm["lanes"]:
            wave, data = lane_wave(ln, cols[did], notes)
            lanes.append({"_id": ln["id"], "_kind": "lane", "_dom": did, "_per": per,
                          "wave": wave, "data": data, "_lane": ln})
    h, sx = choose_scale(lanes, skin, multi)
    fit_labels(lanes, UNIT_PX[skin] * h * sx, notes)
    edges, arrows_meta, nodes = _arrows(d, lanes, cols, notes)
    clock_of = {dm["id"]: dm["clock"] for dm in doms}
    gap_meta, top = _gap_row(plans, lanes, cols, offs, u, clock_of, edges)
    empty = _empty_gaps(plans, notes)
    signal: list = []
    if top:
        signal.append({"name": "", "node": top})
    flat = [{"kind": "gaprow", "id": "gaprow", "cols": []}] if top else []
    for dm in doms:
        grp: list = [f"{dm['clock']} {_period(dm['period'], d)}"]
        for ln in (x for x in lanes if x["_dom"] == dm["id"]):
            sig = {"name": ln["_lane"]["signal"] if ln["_kind"] == "lane" else dm["clock"],
                   "wave": ln["wave"]}
            if ln["data"]:
                sig["data"] = ln["data"]
            if ln["_per"] != 1:
                sig["period"] = ln["_per"]
            ph = -offs[dm["id"]] * h / u
            if ph:
                sig["phase"] = int(ph) if float(ph).is_integer() else ph
            if nodes.get(ln["_id"]):
                sig["node"] = "".join(nodes[ln["_id"]])
            grp.append(sig)
            flat.append({"kind": ln["_kind"], "id": ln["_id"], "domain": dm["id"],
                         "cols": [_col_json(c) for c in cols[dm["id"]]],
                         "drawn": _drawn_values(ln, cols[dm["id"]])})
        signal.append(grp)
    kinds = {a["kind"] for a in arrows_meta}
    stim, legend = _foot(d, kinds, bool(gap_meta))
    title = f"{d.get('id', '')}  —  {d.get('protocol', '')} {d.get('scenario', '')}"
    wj = {"signal": signal, "edge": edges,
          "config": {"hscale": h, "skin": skin},
          "head": {"text": title.strip()},
          "foot": {"text": stim},
          "rtl2d": {"grid": {"unit": u, "t0": t0, "hscale": h, "skin": skin,
                             "periods": periods, "offsets": offs,
                             "squeeze": sx, "px_raw": UNIT_PX[skin] * h,
                             "px_per_unit": UNIT_PX[skin] * h * sx},
                    "legend": legend,
                    "signals": flat, "arrows": arrows_meta, "gaps": gap_meta,
                    "empty_gaps": empty, "domains": [dm["id"] for dm in doms],
                    "sampling": "value held during the cycle that ends at the sample's "
                    "posedge (x4 vcd.py: last change strictly before the edge)",
                    "simplifications": notes}}
    return wj, notes


def _col_json(c: Col) -> list:
    return [c.kind, c.cycle, c.gap, int(c.mark)]


def _drawn_values(ln: dict, cols: list[Col]) -> list | None:
    if ln["_kind"] != "lane":
        return None
    out, di, cur = [], 0, None
    for ch, c in zip(ln["wave"], cols, strict=True):
        if ch == "=":
            cur = ln["data"][di]
            di += 1
        elif ch in "01xz":
            cur = ch
        out.append(cur if c.kind == "s" else None)
    return out


def _arrows(d: dict, lanes: list[dict], cols: dict, notes: list[dict]):
    by_id = {ln["_id"]: ln for ln in lanes}
    nodes: dict[str, list[str]] = {}
    letters: dict[tuple[str, int], str] = {}
    edges, meta = [], []
    pool = iter(NODE_POOL)
    for a in d.get("arrows") or []:
        ends = []
        for e in (a["src"], a["dst"]):
            ln = by_id.get(e["lane"])
            idx = None
            if ln is not None:
                idx = next((i for i, c in enumerate(cols[ln["_dom"]])
                            if c.kind == "s" and c.cycle == e["cycle"]), None)
            ends.append((e["lane"], idx, ln))
        if any(i is None for _, i, _ in ends):
            notes.append({"what": f"arrow {a['id']} not drawn",
                          "reason": "an end is not on a drawn column"})
            continue
        chars = []
        for lane_id, idx, ln in ends:
            key = (lane_id, idx)
            if key not in letters:
                ch = next(pool, None)
                if ch is None:
                    notes.append({"what": f"arrow {a['id']} not drawn",
                                  "reason": f"more than {len(NODE_POOL)} arrow ends"})
                    break
                letters[key] = ch
                row = nodes.setdefault(lane_id, ["."] * len(ln["wave"]))
                row[idx] = ch
            chars.append(letters[key])
        if len(chars) != 2:
            continue
        edge = f"{chars[0]}{EDGE.get(a['kind'], '->')}{chars[1]}"
        edges.append(edge)
        meta.append({"id": a["id"], "edge": edge, "kind": a["kind"],
                     "src": [a["src"]["lane"], a["src"]["cycle"]],
                     "dst": [a["dst"]["lane"], a["dst"]["cycle"]]})
    return edges, meta, nodes


def _gap_row(plans, lanes, cols, offs, u, clock_of, edges):
    """Top row with one hidden node per gap carrying the '+N cyc' text (a self-edge label)."""
    shown = [p for p in plans if any(p.hidden.values())]
    if not shown:
        return [], ""
    xs = []
    for p in shown:
        best = None
        for did, cs in cols.items():
            per = next(ln["_per"] for ln in lanes if ln["_dom"] == did)
            idx = [i for i, c in enumerate(cs) if c.kind == "hold" and c.gap == p.id]
            if idx:
                i = next((i for i in idx if cs[i].mark), idx[0])  # over the glyph if any
                x = (i * per * u + offs[did]) / u + per / 2  # base units, char centre
                best = x if best is None else min(best, x)
        xs.append(best)
    width = max(len(ln["wave"]) * ln["_per"] for ln in lanes) + 1
    row = ["."] * width
    meta, used = [], iter("abcdefghijklmnopqrstuvwxyz")
    pool = [c for c in reversed(NODE_POOL) if not any(c in e for e in edges)]
    for p, x in zip(shown, xs, strict=True):
        label = _gap_label(p, clock_of)
        pos = max(0, int(x if x is not None else 0))
        while pos < width and row[pos] != ".":
            pos += 1
        ch = pool.pop(0) if pool else next(used)
        row = row + ["."] * max(0, pos + 1 - len(row))
        row[pos] = ch
        edge = f"{ch}-{ch} {label}"
        edges.append(edge)
        meta.append({"id": p.id, "edge": edge, "label": label,
                     "dx_units": (x - pos) if x is not None else 0.0, "after_t": p.after_t,
                     "until_t": p.until_t, "hidden": p.hidden, "declared": p.declared,
                     "removed_t": p.removed, "implicit": p.implicit})
    return meta, "".join(row).rstrip(".")


def _empty_gaps(plans: list[GapPlan], notes: list[dict]) -> list[dict]:
    """Gaps that hide no cycle in any domain: no glyph, no label; tagged as an empty <g>."""
    out = []
    for p in plans:
        if any(p.hidden.values()):
            continue
        out.append({"id": p.id, "after_t": p.after_t, "until_t": p.until_t,
                    "declared": p.declared, "hidden": p.hidden})
        notes.append({"what": f"{p.id} ({p.after_t}..{p.until_t}) hides no cycle "
                      f"({p.hidden or p.declared}); not drawn",
                      "reason": "nothing between two consecutive drawn cycles; tagged as an "
                      "empty <g> for the round trip"})
    return out


# --------------------------------------------------------------------------- render + tag


def render(wj: dict, json_path: Path, svg_path: Path, wavedrom_cmd: list[str],
           timeout: float = 120.0) -> str:
    json_path.write_text(json.dumps(wj, indent=1, ensure_ascii=False), encoding="utf-8")
    raw = svg_path.with_name(svg_path.name + ".raw")
    try:
        r = subprocess.run([*wavedrom_cmd, "-i", str(json_path), "-s", str(raw)],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"wavedrom-cli could not run ({wavedrom_cmd[0]}): {e}") from e
    if r.returncode != 0 or not raw.exists():
        raise RuntimeError(f"wavedrom-cli failed ({r.returncode}): {r.stderr.strip()[:500]}")
    text = raw.read_text(encoding="utf-8")
    raw.unlink()
    return text


def tag_svg(svg_text: str, wj: dict) -> str:
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    root = ET.fromstring(svg_text)
    meta = wj["rtl2d"]
    gs = {el.get("id"): el for el in root.iter(f"{{{SVG_NS}}}g") if el.get("id")}
    for i, s in enumerate(meta["signals"]):
        el = gs.get(f"wavelane_{i}_0")
        if el is None or not s["id"]:
            continue
        el.set("data-rtl2d-kind", s["kind"])
        el.set("data-rtl2d-id", s["id"])
        gap = gs.get(f"wavegap_{i}_0")
        if gap is not None:
            gap.set("data-rtl2d-lane", s["id"])
    arcs = gs.get("wavearcs_0")
    if arcs is not None:
        _tag_arcs(arcs, meta, root, meta["grid"]["px_raw"])
    _tag_groups(gs, meta)
    for e in meta.get("empty_gaps", []):
        el = ET.SubElement(root, f"{{{SVG_NS}}}g", {"data-rtl2d-kind": "gap",
                                                    "data-rtl2d-id": e["id"],
                                                    "data-rtl2d-empty": "1"})
        ET.SubElement(el, f"{{{SVG_NS}}}title").text = (
            f"{e['id']}: {e['after_t']}..{e['until_t']} hides no cycle")
    _thin_marks(root, gs, wj)
    if meta["grid"]["squeeze"] < 1:
        _squeeze(root, gs, meta["grid"]["squeeze"])
    _footer(root, gs, wj)
    return ET.tostring(root, encoding="unicode")


def _tag_arcs(arcs: ET.Element, meta: dict, root: ET.Element, px_unit: float) -> None:
    """WaveDrom draws one path per edge in source order (a self-edge's label <g> follows its
    path); walk them in that order: arrows first, then gap labels."""
    kids = list(arcs)
    pos = 0
    items = [("arrow", a) for a in meta["arrows"]] + [("gap", g) for g in meta["gaps"]]
    for kind, m in items:
        word = m["edge"].split()[0]
        pid = f"gmark_{word[0]}_{word[-1]}"
        while pos < len(kids) and kids[pos].get("id") != pid:
            pos += 1
        if pos >= len(kids):
            return
        el = kids[pos]
        pos += 1
        if kind == "arrow":
            el.set("data-rtl2d-kind", "arrow")
            el.set("data-rtl2d-id", m["id"])
            el.set("data-rtl2d-arrow", m["kind"])
            if m["kind"] == "cdc":
                el.set("style", f"marker-end:url(#arrowhead_cdc);stroke:{C_CDC};"
                       "stroke-width:1.2;stroke-dasharray:4,3;fill:none")
                _cdc_marker(root)
            continue
        lab = kids[pos] if pos < len(kids) and kids[pos].tag == f"{{{SVG_NS}}}g" else None
        target = lab if lab is not None else el
        target.set("data-rtl2d-kind", "gap")
        target.set("data-rtl2d-id", m["id"])
        if lab is not None and m.get("dx_units"):
            x, y = (float(v) for v in re.findall(r"-?[\d.]+", lab.get("transform", "0,0"))[:2])
            lab.set("transform", f"translate({x + m['dx_units'] * px_unit:.1f},{y:g})")


def _tag_groups(gs: dict, meta: dict) -> None:
    """Domain group brackets + labels (WaveDrom: path group_<i>_0, then a <g> with the text)."""
    holder = gs.get("groups_0")
    if holder is None:
        return
    for inner in holder.findall(f"{{{SVG_NS}}}g"):
        kids = list(inner)
        for j, el in enumerate(kids):
            gid = el.get("id") or ""
            if not gid.startswith("group_"):
                continue
            i = int(gid.split("_")[1])
            if i >= len(meta.get("domains", [])):
                continue
            for x in (el, kids[j + 1] if j + 1 < len(kids) else None):
                if x is not None:
                    x.set("data-rtl2d-kind", "domain")
                    x.set("data-rtl2d-id", meta["domains"][i])


def _cdc_marker(root: ET.Element) -> None:
    defs = root.find(f"{{{SVG_NS}}}defs")
    if defs is None or defs.find(f"{{{SVG_NS}}}marker[@id='arrowhead_cdc']") is not None:
        return
    base = defs.find(f"{{{SVG_NS}}}marker[@id='arrowhead']")
    if base is None:
        return
    m = ET.fromstring(ET.tostring(base))
    m.set("id", "arrowhead_cdc")
    m.set("style", f"fill:{C_CDC}")
    defs.append(m)


def _thin_marks(root: ET.Element, gs: dict, wj: dict) -> None:
    """Multi-domain grids: keep only the dotted marks on the fastest clock's posedges."""
    grid = wj["rtl2d"]["grid"]
    if len(grid["periods"]) < 2:
        return
    fast = min(grid["periods"], key=lambda k: grid["periods"][k])
    step = grid["periods"][fast] // grid["unit"]
    first = (grid["offsets"][fast] // grid["unit"]) % step
    marks = gs.get("gmarks_0")
    if marks is None:
        return
    for holder in marks.iter(f"{{{SVG_NS}}}g"):
        for ln in list(holder.findall(f"{{{SVG_NS}}}line")):
            idx = int(ln.get("id", "gmark_0_0").split("_")[1])
            if (idx - first) % step:
                holder.remove(ln)


def _socket_x(root: ET.Element) -> float:
    for g in root.iter(f"{{{SVG_NS}}}g"):
        if g.get("id") == "socket":
            r = g.find(f"{{{SVG_NS}}}rect")
            return float(r.get("x", 6)) if r is not None else 6.0
    return 6.0


def _num_tr(el: ET.Element) -> tuple[float, float]:
    v = re.findall(r"-?[\d.]+", el.get("transform", "") or "0,0")
    return (float(v[0]) if v else 0.0), (float(v[1]) if len(v) > 1 else 0.0)


def _squeeze_path(d: str, sx: float, xl: float) -> str:
    """Scale x of a WaveDrom arc path ('M x,y c ...', 'm x,y dx,dy ...', 'M x,y x,y')."""
    toks = re.findall(r"[MmCcLl]|-?[\d.]+(?:e-?\d+)?", d)
    out, cmd, first, k = [], "M", True, 0
    for tok in toks:
        if tok in "MmCcLl":
            cmd, k = tok, 0
            out.append(tok)
            continue
        v = float(tok)
        if k % 2 == 0:
            absolute = cmd in "MCL" or (cmd == "m" and first)
            v = (v - xl) * sx + xl if absolute else v * sx
        else:
            first = False
        k += 1
        out.append(f"{v:.2f}")
    return " ".join(out)


def _squeeze(root: ET.Element, gs: dict, sx: float) -> None:
    """Shrink the wave area horizontally by sx; text keeps its size (counter-scaled)."""
    xl = _socket_x(root)
    style = root.find(f"{{{SVG_NS}}}style")
    if style is not None:
        style.text = (style.text or "") + "path{vector-effect:non-scaling-stroke}"
    for ln in gs["gmarks_0"].iter(f"{{{SVG_NS}}}line") if "gmarks_0" in gs else []:
        for k in ("x1", "x2"):
            ln.set(k, f"{float(ln.get(k, 0)) * sx:.2f}")
    for gid, el in gs.items():
        if gid.startswith("wavelane_draw_"):
            el.set("transform", f"scale({sx},1)")
            for t in el.iter(f"{{{SVG_NS}}}text"):
                t.set("x", f"{(float(t.get('x', 0)) - xl) * sx + xl:.2f}")
                t.set("transform", f"scale({1 / sx:.6f},1)")
        elif gid.startswith("wavegap_"):
            for u in el.iter(f"{{{SVG_NS}}}use"):
                x, _ = _num_tr(u)
                u.set("transform", f"translate({x * sx:.2f})")
    for el in list(gs.get("wavearcs_0", [])):
        if el.tag == f"{{{SVG_NS}}}path":
            el.set("d", _squeeze_path(el.get("d", ""), sx, xl))
        elif el.get("transform"):
            x, y = _num_tr(el)
            el.set("transform", f"translate({(x - xl) * sx + xl:.2f},{y:g})")
    lanes = gs.get("lanes_0")
    tx = _num_tr(lanes)[0] if lanes is not None else 0.0
    w = float(root.get("width", 0))
    _resize(root, tx + (w - tx) * sx + 10, float(root.get("height", 0)))
    for t in gs["gmarks_0"].findall(f"{{{SVG_NS}}}text") if "gmarks_0" in gs else []:
        t.set("x", f"{float(t.get('x', 0)) * sx:.2f}")


def _resize(root: ET.Element, w: float, h: float) -> None:
    root.set("width", f"{w:.0f}")
    root.set("height", f"{h:.0f}")
    root.set("viewBox", f"0 0 {w:.0f} {h:.0f}")
    for r in root.iter(f"{{{SVG_NS}}}rect"):
        if r.get("style", "").startswith("stroke:none;fill:white"):
            r.set("width", f"{w:.0f}")
            r.set("height", f"{h:.0f}")


def _footer(root: ET.Element, gs: dict, wj: dict) -> None:
    """Left-align the stimulus line and add the legend as a second line (WaveDrom centres one
    foot line on the wave area, which clips long text)."""
    marks = gs.get("gmarks_0")
    lanes = gs.get("lanes_0")
    if marks is None or lanes is None:
        return
    tx, _ = _num_tr(lanes)
    foot_txt = wj["foot"]["text"]
    foot = next((t for t in marks.findall(f"{{{SVG_NS}}}text")
                 if "".join(t.itertext()) == foot_txt), None)
    if foot is None:
        return
    foot.set("data-rtl2d-kind", "footer")
    foot.set("data-rtl2d-id", "footer")
    head = next((t for t in marks.findall(f"{{{SVG_NS}}}text")
                 if "".join(t.itertext()) == wj["head"]["text"]), None)
    if head is not None:
        head.set("data-rtl2d-kind", "title")
        head.set("data-rtl2d-id", "title")
    foot.set("x", f"{12 - tx:.0f}")
    foot.set("text-anchor", "start")
    foot.set("style", "font-size:9pt")
    y = float(foot.get("y", 0))
    legend = wj["rtl2d"].get("legend")
    w, h = float(root.get("width", 0)), float(root.get("height", 0))
    lines = [foot_txt]
    if legend:
        leg = ET.SubElement(marks, f"{{{SVG_NS}}}text", {
            "x": f"{12 - tx:.0f}", "y": f"{y + 17:g}", "text-anchor": "start",
            "style": "font-size:9pt;fill:#0041c4", "data-rtl2d-kind": "legend",
            "data-rtl2d-id": "legend"})
        leg.text = legend
        lines.append(legend)
        h += 17
    need = 12 + max(len(x) for x in lines) * 6.1 + 12  # 9pt Helvetica estimate
    _resize(root, max(w, need), h)


# --------------------------------------------------------------------------- API


_UNIT = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12, "fs": 1e-15}


def _period(period: int, d: dict) -> str:
    """Clock period as text in ns/ps/us, from the stimulus timescale (e.g. "1ps")."""
    ts = str((d.get("stimulus") or {}).get("timescale") or "")
    m = re.fullmatch(r"\s*(\d+)\s*([munpf]?s)\s*", ts)
    if not m:
        return f"T={period}"
    sec = period * int(m.group(1)) * _UNIT[m.group(2)]
    for unit in ("us", "ns", "ps"):
        v = sec / _UNIT[unit]
        if v >= 1:
            return f"T={v:g} {unit}"
    return f"T={period}"


def draw(d: dict, out_stem: Path, *, wavedrom_cmd: list[str]) -> dict:
    """Write out_stem.wavedrom.json and out_stem.svg; return their paths and measures."""
    if not wavedrom_cmd:
        raise RuntimeError("no WaveDrom renderer (wavedrom_cmd is empty)")
    out_stem = Path(out_stem)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    wj, notes = to_wavejson(d)
    p_json, p_svg = Path(f"{out_stem}.wavedrom.json"), Path(f"{out_stem}.svg")
    svg = tag_svg(render(wj, p_json, p_svg, wavedrom_cmd), wj)
    p_svg.write_text(svg, encoding="utf-8")
    meas = _sibling("wave_measure").measure(svg, wj)
    return {"svg": str(p_svg), "wavejson": str(p_json), "measure": meas,
            "simplifications": notes}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("timing_json")
    ap.add_argument("out_stem")
    ap.add_argument("--node", required=True)
    ap.add_argument("--cli", required=True)
    a = ap.parse_args(argv)
    d = json.loads(Path(a.timing_json).read_text(encoding="utf-8"))
    print(json.dumps(draw(d, Path(a.out_stem), wavedrom_cmd=[a.node, a.cli]), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
