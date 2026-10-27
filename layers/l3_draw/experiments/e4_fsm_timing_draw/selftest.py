"""e4 self-test: draw the hand-written fixtures, run the round trips, print the measures.

    uv run --package rtl2d-l3 python layers/l3_draw/experiments/e4_fsm_timing_draw/selftest.py \
        [--out runs/e4_fsm_timing_draw] [--node PATH] [--cli PATH] [--png]

The WaveDrom renderer defaults to $RTL2D_TOOLS (else <repo>/runs/.tools)/x3/node/bin/node and
.../wavedrom/node_modules/wavedrom-cli/wavedrom-cli.js. --png also rasterizes every SVG with
rsvg-convert for looking at. Also feeds tampered drawings / inputs to the round trips, which
must reject them. Exit 1 if any round trip fails or a tampered case passes.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def _mod(name: str):
    key = f"e4_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def _png(svg: str) -> None:
    exe = shutil.which("rsvg-convert")
    if exe:
        subprocess.run([exe, "-b", "white", svg, "-o", svg[:-4] + ".png"], check=False,
                       timeout=60)


def run_fsm(out: Path, png: bool) -> bool:
    fx, draw, rt = _mod("fixtures"), _mod("fsm_draw"), _mod("fsm_roundtrip")
    ok = True
    for name, make in fx.FSMS.items():
        g = make()
        r = draw.draw(g, out / name)
        c = rt.check(g, Path(r["svg"]).read_text(encoding="utf-8"))
        ok &= c["ok"]
        m = r["measure"]
        print(f"{name:18s} G4 {'ok' if c['ok'] else 'FAIL'} states {c['states']} "
              f"transitions {c['transitions']} | {m['width']:.0f}x{m['height']:.0f}pt "
              f"cross {m['crossings']} label_ov {m['label_overlaps']} "
              f"hits {m['label_hits']} back {m['back_edges']} loops {m['self_loops']} "
              f"| simpl {len(r['simplifications'])}")
        if not c["ok"]:
            print("   ", json.dumps(c))
        if png:
            _png(r["svg"])
    return ok


def run_wave(out: Path, cmd: list[str], png: bool) -> bool:
    fx, draw, chk = _mod("fixtures"), _mod("wave_draw"), _mod("wave_check")
    ok = True
    for name, make in fx.TIMINGS.items():
        d = make()
        r = draw.draw(d, out / name, wavedrom_cmd=cmd)
        wj = json.loads(Path(r["wavejson"]).read_text(encoding="utf-8"))
        c = chk.check(d, Path(r["svg"]).read_text(encoding="utf-8"), wj)
        ok &= c["ok"]
        m = r["measure"]
        print(f"{name:18s} T5 {'ok' if c['ok'] else 'FAIL'} lanes {c['lanes_found']} "
              f"arrows {c['arrows_found']} gaps {c['gaps_found']} | {m['width']:.0f}x"
              f"{m['height']:.0f}px grid {m['grid']} collide {m['label_collisions']} "
              f"overflow {m['label_overflows']} cross {m['arrow_crossings']} "
              f"cycles {m['cycles']} | simpl {len(r['simplifications'])}")
        for s in r["simplifications"]:
            print("    simplification:", s["what"], "--", s["reason"])
        if not c["ok"]:
            print("   ", json.dumps(c))
        if png:
            _png(r["svg"])
    return ok


def run_negative(out: Path, cmd: list[str]) -> bool:
    """Tampered inputs that the round trips must reject (review findings of 2026-10-24)."""
    fx, wd, chk = _mod("fixtures"), _mod("wave_draw"), _mod("wave_check")
    fd, rt = _mod("fsm_draw"), _mod("fsm_roundtrip")
    d = fx.timing_single()
    r = wd.draw(d, out / "neg_timing", wavedrom_cmd=cmd)
    svg = Path(r["svg"]).read_text(encoding="utf-8")
    wj = json.loads(Path(r["wavejson"]).read_text(encoding="utf-8"))
    relabel = copy.deepcopy(wj)
    for m in relabel["rtl2d"]["signals"]:
        if m["id"] == "l.2":
            m["cols"] = [["hold", None, None, 0] if c[0] == "s" else c for c in m["cols"]]
    extra = copy.deepcopy(d)
    extra["domains"][0]["lanes"][0]["values"].append({"cycle": 50, "t": 505, "v": "1"})
    shifted = copy.deepcopy(wj)
    shifted["rtl2d"]["grid"]["offsets"]["d.clk"] += 10
    g = {"module": "m", "state_reg": "st", "width": 1, "encoding": "binary",
         "states": [{"id": "s.A", "name": "A", "value": 0, "reset": True}],
         "transitions": [{"id": "t.0", "src": "s.A", "dst": "s.GHOST", "guard": "x",
                          "guard_kind": "expr", "seen_by": ["syntactic"]}]}
    rf = fd.draw(g, out / "neg_dangling")
    cases = {"sample columns relabelled hold": chk.check(d, svg, relabel)["ok"],
             "undrawn extra sample": chk.check(extra, svg, wj)["ok"],
             "grid offset shifted": chk.check(d, svg, shifted)["ok"],
             "dangling transition end": rt.check(g, Path(rf["svg"]).read_text())["ok"]}
    for k, v in cases.items():
        print(f"negative: {k:32s} {'caught' if not v else 'NOT CAUGHT'}")
    return not any(cases.values())


def main(argv: list[str]) -> int:
    tools = Path(os.environ.get("RTL2D_TOOLS", ROOT / "runs" / ".tools"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "runs" / "e4_fsm_timing_draw"))
    ap.add_argument("--node", default=str(tools / "x3" / "node" / "bin" / "node"))
    ap.add_argument("--cli", default=str(tools / "wavedrom" / "node_modules" / "wavedrom-cli"
                                         / "wavedrom-cli.js"))
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    ok = run_fsm(out / "fsm", a.png)
    ok &= run_wave(out / "timing", [a.node, a.cli], a.png)
    ok &= run_negative(out / "negative", [a.node, a.cli])
    print("ALL OK" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
