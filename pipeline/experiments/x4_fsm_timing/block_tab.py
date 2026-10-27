"""x4 block tab: the block diagram of an arbitrary design {name, files, top}, drawn with the
existing block prototype (x1 bridge = L2 stand-in #1, x2 adapter, e3 paper engines), with
L1 in pure heuristic mode (no teacher-v1 archive, no Run Store, no API).

    uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/block_tab.py \\
        --files layers/l1_extract/data/rtl/wb2axip/rtl/skidbuffer.v --top skidbuffer \\
        --out runs/x4_fsm_timing/block_demo/skidbuffer [--engine dot] [--timeout 300]

`draw_block(entry, out_dir)` runs the chain in a child process (this file with `--worker`)
under `x4_tools.run_capped` (wall-clock timeout + cgroup memory cap): x1/x2/e3 put their own
directories on `sys.path` and import each other by plain module names (`bridge`, `paper`,
`check`, `layout`, ...), so keeping them in a child keeps the orchestrator's module table
clean, and a slow or oversize design cannot hang or sink the caller.

Chain (the same as x2 `bridge_one` + `draw_one`, minus teacher-v1):
  x1 bridge.build(entry)            L1 annotate_design (heuristic) -> e0 diagram + meta
  e0 spec.validate                  full ADR-0002 v0.1 rules on the bridge diagram (reported)
  x2 adapter.adapt / adapter.check  collapse wiring blocks, groups, hubs; rules 1-7 enforced
  x2 draw_one(job)                  e3 grammar -> layout (dot) -> libavoid -> paper SVG,
                                    e3 check.roundtrip, measure3, PNG preview (rsvg-convert)
Output under out_dir: inputs/<name>.{bridge,meta,diagram,side}.json, svg/<name>/<engine>.svg,
png/<name>/<engine>.png, block.json (the returned dict plus the x2 draw row), worker.log.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import re
import shutil
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
X1 = ROOT / "pipeline" / "experiments" / "x1_l1_to_l3"
X2 = ROOT / "pipeline" / "experiments" / "x2_l1_to_paper"
DEFAULT_TIMEOUT = 300.0


def _tools():
    """x4_tools, shared with x4_run.py when it already loaded it (same module name)."""
    if "x4_tools" in sys.modules:
        return sys.modules["x4_tools"]
    spec = importlib.util.spec_from_file_location("x4_tools", HERE / "x4_tools.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["x4_tools"] = mod
    spec.loader.exec_module(mod)
    return mod


def _abs(p: str | Path) -> str:
    q = Path(p)
    return str(q if q.is_absolute() else (ROOT / q).resolve())


def pick_engine() -> str:
    """Graphviz dot when it is on PATH (no node needed), else ELK layered."""
    return "dot" if shutil.which("dot") else "elk"


def _result(ok: bool, svg: Path | None, error: str | None, notes: list[str]) -> dict:
    return {"svg_path": str(svg) if svg else None, "ok": ok, "error": error, "notes": notes}


# ------------------------------------------------------------------ parent side
def draw_block(entry: dict, out_dir: Path, *, engine: str | None = None,
               timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Block diagram of `entry` = {name, files, top[, include_dirs, defines]} into `out_dir`.

    Returns {svg_path, ok, error, notes}. Never raises on a drawing failure: a failed stage,
    a timeout or a crash of the child comes back as ok=False with a one-line error."""
    out_dir = Path(_abs(out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    eng = engine or pick_engine()
    job = {"name": entry.get("name") or entry["top"], "top": entry["top"],
           "files": [_abs(f) for f in entry["files"]],
           "include_dirs": [_abs(d) for d in entry.get("include_dirs") or []],
           "defines": list(entry.get("defines") or []), "engine": eng}
    (out_dir / "entry.json").write_text(json.dumps(job, indent=1), encoding="utf-8")
    res_file = out_dir / "block.json"
    res_file.unlink(missing_ok=True)
    t0 = time.perf_counter()
    r = _tools().run_capped([sys.executable, str(HERE / "block_tab.py"), "--worker",
                             str(out_dir / "entry.json"), str(out_dir)],
                            cwd=ROOT, timeout=timeout)
    secs = round(time.perf_counter() - t0, 1)
    (out_dir / "worker.log").write_text((r.stdout or "") + "\n--- stderr ---\n"
                                        + (r.stderr or ""), encoding="utf-8")
    if r.returncode == 124:
        return _result(False, None, f"block diagram timed out after {timeout:g} s "
                       f"(engine {eng})", [f"see {out_dir / 'worker.log'}"])
    if not res_file.exists():
        tail = ((r.stderr or r.stdout or "").strip().splitlines() or ["no output"])[-1]
        return _result(False, None, f"block worker exited {r.returncode} without a result "
                       f"(killed by the memory cap?): {tail[:200]}", [])
    res = json.loads(res_file.read_text(encoding="utf-8"))
    res["notes"] = [*res.get("notes", []), f"block worker {secs} s, engine {eng}"]
    return {k: res.get(k) for k in ("svg_path", "ok", "error", "notes")}


# ------------------------------------------------------------------ child side
def _load_chain():
    """x2's run.py does the x1/x2/e3 path setup (and through p3lib the e0/e1/e2 one) and
    imports `adapter` and `p3lib`; x1's bridge is loaded under its own name."""
    t = _tools()
    x2run = t.load(X2 / "run.py", "x2_run")
    bridge = t.load(X1 / "bridge.py", "x1_bridge")
    return x2run, bridge


def _heuristic_annotate(entry: dict, runs: list):
    """Replacement for bridge.annotate_design: heuristic L1, no store, no teacher, no API.
    Every DesignRun it returns is also appended to `runs` (for L1 diagnostics)."""
    from rtl2d_l1.pipeline import RunConfig, annotate_design

    def annotate(files, *, top=None, cfg=None, store=None, **kw):  # noqa: ARG001
        run = annotate_design(files, top=top, cfg=RunConfig(mode="heuristic"),
                              include_dirs=entry.get("include_dirs") or None,
                              defines=entry.get("defines") or None)
        runs.append(run)
        return run

    return annotate


def l1_diagnostics(runs: list) -> tuple[list[str], list[str]]:
    """(errors, warnings) of the L1 elaborations, deduplicated, in order."""
    errs = list(dict.fromkeys(str(e) for r in runs for e in r.design.errors))
    warns = list(dict.fromkeys(str(w) for r in runs for w in (r.design.warnings or [])))
    return errs, warns


VALID = re.compile(r"valid|vld", re.I)
READY = re.compile(r"ready|rdy", re.I)


def _handshakes(ports: list[str]) -> list[tuple[str, str]]:
    """(valid, ready) port pairs of one bundle: same name once valid/ready is cut out; if no
    name pairs up and the bundle has exactly one of each, that one pair."""
    leaf = {p: p.split(".")[-1] for p in ports}
    vs = [p for p in ports if VALID.search(leaf[p])]
    rs = [p for p in ports if READY.search(leaf[p])]
    stem = {p: (VALID if p in vs else READY).sub("", leaf[p]) for p in vs + rs}
    pairs = [(v, r) for v in vs for r in rs if stem[v] == stem[r]]
    if not pairs and len(vs) == 1 and len(rs) == 1:
        pairs = [(vs[0], rs[0])]
    return pairs


def suspect_bundles(meta: dict, d: dict) -> list[tuple[str, str]]:
    """L1 VALID_READY bundles with a valid/ready pair running the same way (a real handshake
    has ready against valid), e.g. skidbuffer i = {i_valid, i_data, i_ready}: [(name, why)]."""
    dirs = {p["id"]: p["direction"] for p in d["ports"]}
    out = []
    for i in meta.get("interfaces") or []:
        if i.get("protocol") != "VALID_READY":
            continue
        same = [(v, r) for v, r in _handshakes(i["ports"]) if dirs.get(v) == dirs.get(r)]
        if same:
            v, r = same[0]
            names = ", ".join(p.split(".")[-1] for p in i["ports"])
            out.append((i["name"], f"{{{names}}}: {v.split('.')[-1]} and {r.split('.')[-1]} "
                                   f"are both {dirs.get(v)}s"))
    return out


def _unbundle(side: dict, meta: dict, d: dict) -> list[str]:
    """Drop mis-paired L1 bundles from the e3 pin groups so their ports are drawn one by one."""
    bad = suspect_bundles(meta, d)
    if not bad:
        return []
    names = {n for n, _ in bad}
    side["pin_groups"] = {p: g for p, g in side.get("pin_groups", {}).items() if g not in names}
    return [f"simplification: L1 port bundle {n} {why} (L1 mis-pairing); not bundled, its "
            f"ports are drawn separately (reason: a wrong bundle would draw a wrong handshake)"
            for n, why in bad]


def _hidden_global(nd: dict) -> str | None:
    """Note for the clock/reset nets the e3 grammar leaves out (grammar rule 1)."""
    names = sorted(n["id"].removeprefix("n.") for n in nd["nets"]
                   if n.get("class") in ("clock", "reset"))
    if not names:
        return None
    return (f"simplification: {len(names)} clock/reset net(s) not drawn ({', '.join(names[:8])}"
            f"{', ...' if len(names) > 8 else ''}) (reason: e3 grammar rule 1, global nets)")


def symbol_diagram(d: dict, top: str) -> dict:
    """One box for the top module, every top port wired to a pin of that box. Used when the
    bridge has no unit to draw (a leaf module: no child instance, and heuristic L1 forms no
    logic group), so the tab shows the module's interface instead of an empty sheet."""
    bid = "b." + "".join(c if c.isalnum() or c in "_.-" else "_" for c in top)
    blocks = [{"id": bid, "label": top, "kind": None, "parent_id": None}]
    ports, nets = [], []
    for p in d["ports"]:
        if p["owner_block_id"] is not None:
            continue
        name = p["id"].split(".", 1)[-1]
        inner = {"id": f"{bid}.{name}", "owner_block_id": bid, "direction": p["direction"],
                 "width": p["width"], "class": p.get("class")}
        ports += [dict(p), inner]
        src, dst = (p["id"], inner["id"]) if p["direction"] == "input" else (inner["id"],
                                                                             p["id"])
        nets.append({"id": f"n.{name}", "source": src, "targets": [dst], "width": p["width"],
                     "class": p.get("class")})
    return {"schema_version": d["schema_version"], "blocks": blocks, "ports": ports,
            "nets": nets}


def _units(d: dict) -> int:
    parents = {b["parent_id"] for b in d["blocks"] if b.get("parent_id")}
    return sum(1 for b in d["blocks"] if b["id"] not in parents)


def _bridge_stage(entry: dict, out_dir: Path, x2run, bridge) -> tuple[dict | None, list[str]]:
    """L1 + x1 bridge + x2 adapter. Returns (row, notes); row None with notes on failure."""
    name = entry["name"]
    notes: list[str] = ["labels: L1 heuristic only (teacher-v1 skipped by design)"]
    runs: list = []
    bridge.annotate_design = _heuristic_annotate(entry, runs)
    bridge.RunStore = lambda *_a, **_k: None  # as x2 does; heuristic mode never reads it
    d, _hints, meta = bridge.build(entry)
    errs, warns = l1_diagnostics(runs)
    if warns:
        notes.append(f"L1 elaboration: {len(warns)} warning(s), first: {warns[0]}")
    if errs:
        return None, [*notes, f"L1 elaboration: {len(errs)} error(s) in the RTL, first: "
                              f"{'; '.join(errs[:3])}; no block diagram drawn from it"]
    spec = x2run.p3lib.spec
    bad = spec.validate(spec.Diagram.model_validate(d))
    if bad:
        notes.append(f"bridge diagram: {len(bad)} ADR-0002 rule issue(s), first: {bad[0]}")
    nd, side, anotes = x2run.adapter.adapt(d, meta)
    notes += [f"adapter: {n}" for n in anotes]
    view = meta.get("view")
    if _units(nd) == 0:
        top = meta.get("top") or entry["top"]
        nd = symbol_diagram(d, top)
        view = "module symbol"
        kinds = Counter(str(b.get("kind")) for b in d["blocks"])
        made = (f"the bridge made {len(d['blocks'])} block(s) "
                f"({', '.join(f'{k} x{n}' for k, n in sorted(kinds.items()))}) and the adapter "
                f"collapsed all of them" if d["blocks"] else "the bridge made no block")
        notes.append(f"simplification: module symbol of {top} instead of the bridge view "
                     f"(reason: {made}; the top has no child instance and heuristic L1 forms "
                     f"no logic group, so there is no unit to draw); {len(nd['nets'])} top "
                     f"port(s) wired to the box, grouped by L1 port bundles where they look "
                     f"right")
    notes += _unbundle(side, meta, d)
    hidden = _hidden_global(nd)
    if hidden:
        notes.append(hidden)
    errs, relaxed = x2run.adapter.check(nd)
    if relaxed:
        notes.append(f"adapter relaxed {len(relaxed)} width/one-driver rule(s) (rules 8-9 "
                     f"reported, not enforced), first: {relaxed[0]}")
    inp = out_dir / "inputs"
    inp.mkdir(parents=True, exist_ok=True)
    for k, v in (("bridge", d), ("meta", meta), ("diagram", nd), ("side", side)):
        (inp / f"{name}.{k}.json").write_text(json.dumps(v, indent=1, ensure_ascii=False),
                                              encoding="utf-8")
    if errs:
        return None, [*notes, f"adapter rule errors: {'; '.join(errs[:3])}"]
    notes.append(f"{len(d['blocks'])} bridge blocks / {len(d['nets'])} nets -> "
                 f"{_units(nd)} units / {len(nd['nets'])} nets (view {view})")
    return {"blocks": _units(nd), "nets": len(nd["nets"]), "view": view}, notes


def work(entry: dict, out_dir: Path) -> dict:
    """The whole chain in this process; writes out_dir/block.json and returns its dict."""
    x2run, bridge = _load_chain()
    name, eng = entry["name"], entry["engine"]
    try:
        row, notes = _bridge_stage(entry, out_dir, x2run, bridge)
    except Exception as e:  # noqa: BLE001 - reported as the block tab's error
        traceback.print_exc()
        return _result(False, None, f"L1/bridge: {type(e).__name__}: {str(e)[:300]}", [])
    if row is None:
        return _result(False, None, notes[-1], notes[:-1])
    x2run.OUT = out_dir  # draw_one reads inputs from and writes svg/png under OUT
    draw = x2run.draw_one({"input": name, "engine": eng, "cpsat_seconds": 20.0})
    svg = out_dir / "svg" / name / f"{eng}.svg"
    if draw.get("status") != "ok" or not svg.exists():
        return {**_result(False, None, f"e3 {eng}: {draw.get('error', draw.get('status'))}",
                          notes), "draw": draw}
    rt = draw.get("roundtrip")
    notes.append(f"e3 {eng}: {draw.get('units')} units, {draw.get('edges')} edges, "
                 f"{draw.get('containers')} containers, round-trip issues {rt}, "
                 f"crossings {draw.get('cross')}, {draw.get('width')}x{draw.get('height')} px")
    if rt:
        notes.append(f"e3 round-trip first issue: {draw.get('rt_first')}")
    if draw.get("notes"):
        notes.append(f"layout: {draw['notes']}")
    return {**_result(True, svg, None, notes), "draw": draw, **row}


def _worker(entry_json: str, out_dir: str) -> int:
    entry = json.loads(Path(entry_json).read_text(encoding="utf-8"))
    out = Path(out_dir)
    res = work(entry, out)
    (out / "block.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: res.get(k) for k in ("ok", "svg_path", "error")}), flush=True)
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--worker"]:
        return _worker(argv[1], argv[2])
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="+", required=True)
    ap.add_argument("--top", required=True)
    ap.add_argument("--name")
    ap.add_argument("--out", required=True)
    ap.add_argument("--engine", choices=["dot", "elk"])
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    a = ap.parse_args(argv)
    entry = {"name": a.name or a.top, "files": a.files, "top": a.top}
    res = draw_block(entry, Path(a.out), engine=a.engine, timeout=a.timeout)
    print(json.dumps(res, indent=1))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
