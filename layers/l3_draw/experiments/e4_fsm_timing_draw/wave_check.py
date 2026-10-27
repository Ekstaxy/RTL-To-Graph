"""T5 round trip for WaveDrom timing drawings.

    uv run --package rtl2d-l3 python layers/l3_draw/experiments/e4_fsm_timing_draw/wave_check.py \
        TIMING.json OUT_STEM.svg OUT_STEM.wavedrom.json

Checks, from the SVG and the WaveDrom JSON (wave strings + the "rtl2d" column map that wave_draw
writes next to them); wave_draw's code is never imported, and the column map itself is checked
against the TimingDiagram, not trusted:
- every lane, clock, arrow and declared gap of the TimingDiagram appears exactly once as
  data-rtl2d-kind="lane|clock|arrow|gap" with its id;
- column map: the cycles of a lane's sample columns are exactly the cycles of Lane.values, and
  every sample column, recomputed from the grid (unit, offsets, periods, the time each gap
  removes), ends at its Sample.t (the sample is the value held during the cycle ending at its
  posedge); the WaveDrom period / phase of every signal match the grid;
- replay of the drawing: decoding each lane's wave string (+ data labels) gives, on every drawn
  sample column, the TimingDiagram value (hex, or the enum state name; a label shortened with
  a trailing ellipsis must be a prefix of the value), and on every hidden (gap) or pad column
  the hatched 'x', never a value;
- the data labels inside each SVG lane equal the WaveDrom data list, in order;
- every arrow end letter sits on the column of its (lane, cycle);
- every compressed gap has one '|' glyph in every lane of the domains it spans.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

NS = "{http://www.w3.org/2000/svg}"
ELL = "…"


def flat_signals(wj: dict) -> list[dict]:
    out: list[dict] = []
    for s in wj["signal"]:
        if isinstance(s, list):
            out += [x for x in s[1:] if isinstance(x, dict)]
        elif isinstance(s, dict):
            out.append(s)
    return out


def decode(sig: dict) -> list[str | None]:
    """Value shown under each wave character (None for clock characters)."""
    data = list(sig.get("data") or [])
    out: list[str | None] = []
    cur: str | None = None
    for ch in sig.get("wave", ""):
        if ch == "=":
            cur = data.pop(0) if data else "?"
        elif ch in "01xz":
            cur = ch
        elif ch in "pPnNhlHL":
            cur = None
        out.append(cur)
    return out


def expected(v: str, lane: dict) -> str:
    v = str(v).strip().lower()
    enum = lane.get("enum")
    if enum:
        if v in enum:
            return enum[v]
        for k, name in enum.items():
            try:
                if int(str(k).replace("0x", ""), 16) == int(v, 16):
                    return name
            except ValueError:
                continue
    if lane.get("width", 1) > 1 and (set(v) <= {"x"} or set(v) <= {"z"}):
        return v[0]
    if lane.get("width", 1) == 1 and v not in ("0", "1", "x", "z"):
        return "x"
    return v


def _same(drawn: str | None, want: str) -> tuple[bool, bool]:
    if drawn == want:
        return True, False
    if drawn and drawn.endswith(ELL) and want.startswith(drawn[:-1]):
        return True, True
    return False, False


def svg_tags(root: ET.Element) -> dict[str, Counter]:
    out: dict[str, Counter] = {}
    for el in root.iter():
        k, i = el.get("data-rtl2d-kind"), el.get("data-rtl2d-id")
        if k and i is not None:
            out.setdefault(k, Counter())[i] += 1
    return out


def _lane_texts(root: ET.Element, idx: int) -> list[str]:
    for el in root.iter(f"{NS}g"):
        if el.get("id") == f"wavelane_draw_{idx}_0":
            return ["".join(t.itertext()) for t in el.iter(f"{NS}text")]
    return []


def _gap_glyphs(root: ET.Element, idx: int) -> int:
    for el in root.iter(f"{NS}g"):
        if el.get("id") == f"wavegap_{idx}_0":
            return len(list(el.iter(f"{NS}use")))
    return 0


def _presence(d: dict, tags: dict[str, Counter]) -> tuple[list[str], dict]:
    want = {"lane": [ln["id"] for dm in d["domains"] for ln in dm["lanes"] if ln["values"]],
            "clock": [f"clk.{dm['id']}" for dm in d["domains"]
                      if any(ln["values"] for ln in dm["lanes"])],
            "arrow": [a["id"] for a in d.get("arrows") or []],
            "gap": [f"g.{i}" for i in range(len(d.get("gaps") or []))]}
    missing = []
    for kind, ids in want.items():
        got = tags.get(kind, Counter())
        for i in ids:
            if got[i] != 1:
                missing.append(f"{kind}:{i}" + ("" if got[i] == 0 else f" x{got[i]}"))
    found = {k: sum(1 for i in ids if tags.get(k, Counter())[i] == 1) for k, ids in want.items()}
    return missing, found


def _removed_before(t: int, gaps: list[dict]) -> int:
    return sum(g.get("removed_t", 0) for g in gaps if g["until_t"] <= t)


def _columns(d: dict, wj: dict) -> list[str]:
    """Column map vs TimingDiagram: sample cycles, column end times, WaveDrom period/phase."""
    grid, gaps = wj["rtl2d"]["grid"], wj["rtl2d"]["gaps"]
    u, t0, h = grid["unit"], grid["t0"], grid["hscale"]
    lanes = {ln["id"]: ln for dm in d["domains"] for ln in dm["lanes"]}
    period = {dm["id"]: int(dm["period"]) for dm in d["domains"]}
    bad = []
    for m, sig in zip(wj["rtl2d"]["signals"], flat_signals(wj), strict=False):
        if m["kind"] not in ("lane", "clock"):
            continue
        did = m["domain"]
        per, off = period[did], grid["offsets"][did]
        if sig.get("period", 1) != per // u or per % u:
            bad.append(f"{m['id']}: WaveDrom period {sig.get('period', 1)}, grid {per}/{u}")
        if abs(sig.get("phase", 0) - (-off * h / u)) > 1e-9:
            bad.append(f"{m['id']}: WaveDrom phase {sig.get('phase', 0)}, grid {-off * h / u}")
        if len(sig.get("wave", "")) != len(m["cols"]):
            bad.append(f"{m['id']}: {len(sig.get('wave', ''))} wave chars, "
                       f"{len(m['cols'])} columns")
        if m["kind"] != "lane":
            continue
        ts = {s["cycle"]: s["t"] for s in lanes[m["id"]]["values"]}
        drawn = [c[1] for c in m["cols"] if c[0] == "s"]
        if sorted(drawn) != sorted(ts) or len(set(drawn)) != len(drawn):
            bad.append(f"{m['id']}: sample columns {sorted(drawn)[:6]}... != Lane.values "
                       f"cycles {sorted(ts)[:6]}...")
        for i, c in enumerate(m["cols"]):
            if c[0] == "s" and c[1] in ts:
                t = ts[c[1]]
                if (i + 1) * per + off != t - t0 - _removed_before(t, gaps):
                    bad.append(f"{m['id']} cycle {c[1]}: column {i} ends at "
                               f"{(i + 1) * per + off}, sample t={t} is at "
                               f"{t - t0 - _removed_before(t, gaps)}")
                    break
    return bad


def _replay(d: dict, wj: dict, root: ET.Element) -> tuple[list[str], list[str], int]:
    lanes = {ln["id"]: ln for dm in d["domains"] for ln in dm["lanes"]}
    meta = wj["rtl2d"]["signals"]
    sigs = flat_signals(wj)
    bad_val, bad_lab, short = [], [], 0
    for i, (m, sig) in enumerate(zip(meta, sigs, strict=False)):
        if m["kind"] != "lane":
            continue
        ln = lanes[m["id"]]
        vals = {s["cycle"]: s["v"] for s in ln["values"]}
        shown = decode(sig)
        for col, drawn in zip(m["cols"], shown, strict=False):
            if col[0] != "s":
                if drawn != "x":
                    bad_val.append(f"{m['id']}: {col[0]} column (gap {col[2]}) shows "
                                   f"{drawn!r}, not the hatched 'x'")
                continue
            ok, cut = _same(drawn, expected(vals.get(col[1], "x"), ln))
            short += cut
            if not ok:
                bad_val.append(f"{m['id']} cycle {col[1]}: drawn {drawn!r}, "
                               f"data {vals.get(col[1])!r}")
        if _lane_texts(root, i) != list(sig.get("data") or []):
            bad_lab.append(f"{m['id']}: SVG labels differ from the WaveDrom data list")
    return bad_val, bad_lab, short


def _ends(wj: dict) -> list[str]:
    meta = {m["id"]: (m, s) for m, s in zip(wj["rtl2d"]["signals"], flat_signals(wj),
                                            strict=False) if m["id"]}
    bad = []
    for a in wj["rtl2d"]["arrows"]:
        word = a["edge"].split()[0]
        for (lane, cyc), ch in ((a["src"], word[0]), (a["dst"], word[-1])):
            m, s = meta.get(lane, (None, None))
            node = (s or {}).get("node", "")
            pos = node.find(ch)
            if m is None or pos < 0 or m["cols"][pos][:2] != ["s", cyc]:
                bad.append(f"{a['id']}: end {lane}@{cyc} not on its column")
    return bad


def _gap_marks(wj: dict, root: ET.Element) -> list[str]:
    bad = []
    for i, m in enumerate(wj["rtl2d"]["signals"]):
        if not m["id"]:
            continue
        marks = sum(c[3] for c in m["cols"])
        if _gap_glyphs(root, i) != marks:
            bad.append(f"{m['id']}: {_gap_glyphs(root, i)} gap glyphs, {marks} expected")
    return bad


def check(d: dict, svg_text: str, wavejson: dict) -> dict:
    root = ET.fromstring(svg_text)
    tags = svg_tags(root)
    missing, found = _presence(d, tags)
    bad_val, bad_lab, short = _replay(d, wavejson, root)
    bad_end = _ends(wavejson)
    bad_gap = _gap_marks(wavejson, root)
    bad_col = _columns(d, wavejson)
    return {"ok": not (missing or bad_val or bad_lab or bad_end or bad_gap or bad_col),
            "lanes_found": found["lane"], "clocks_found": found["clock"],
            "arrows_found": found["arrow"], "gaps_found": found["gap"],
            "missing": missing, "value_mismatches": bad_val[:20],
            "label_mismatches": bad_lab, "arrow_end_mismatches": bad_end,
            "gap_glyph_mismatches": bad_gap, "column_mismatches": bad_col[:20],
            "labels_shortened": short}


def main(argv: list[str]) -> int:
    d = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    svg = Path(argv[1]).read_text(encoding="utf-8")
    wj = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    r = check(d, svg, wj)
    print(json.dumps(r, indent=1))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
