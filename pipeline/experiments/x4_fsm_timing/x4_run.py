"""x4: RTL -> FSM graphs and timing diagrams (and the block diagram), end to end.

    uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/x4_run.py \\
        --manifest pipeline/experiments/x4_fsm_timing/manifest_fsm.json --part fsm [--prove]
    uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/x4_run.py \\
        --manifest pipeline/experiments/x4_fsm_timing/manifest_timing.json --part timing
    uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/x4_run.py \\
        --rtl path/to/rtl_dir [--top T] --part block,fsm,timing --out runs/x4_fsm_timing/mine

Stages per design (FORMATS.md):
  L1 annotate_design (heuristic, no API)        -> designs/<d>/l1/
  e8 enrich (L1 experiment)                     -> fsm_ext.json
  e9 select (L1 experiment)                     -> signals.json
  fsm_bridge / fsm_yosys / fsm_prove / checks   -> fsm/<id>.json        (L2 stand-in)
  e4 fsm_draw + round-trip (L3 experiment)      -> fsm/<id>.svg
  sim (x2 for determinism) / timing_bridge      -> sim/, timing/<id>.json (L2 stand-in)
  e4 wave_draw + wave_check (L3 experiment)     -> timing/<id>.svg
  block_tab (x1 bridge + x2 adapter + e3)       -> block/
Output: <out>/{designs/<d>/result.json, results.json, stages.json, rejected.json, gallery.html}
Nothing in any layer's src/ or in contracts/ is changed; layer experiments are loaded through
x4_tools.load().
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("x4_tools", HERE / "x4_tools.py")
x4_tools = importlib.util.module_from_spec(_spec)
sys.modules["x4_tools"] = x4_tools
_spec.loader.exec_module(x4_tools)

RTL_EXT = {".v", ".sv", ".vh", ".svh"}
VARIANT = re.compile(r"^(orig|S1|S2)_(.+)$")


# ------------------------------------------------------------------ inputs
def _abs(p: str) -> str:
    q = Path(p)
    return str(q if q.is_absolute() else (ROOT / q).resolve())


def _modules(text: str) -> dict[str, set[str]]:
    """Declared module name -> identifiers used like `name [#(...)] inst (` in its body."""
    body = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"^\s*module\s+(?:automatic\s+|static\s+)?([A-Za-z_]\w*)(.*?)"
                         r"^\s*endmodule", body, flags=re.M | re.S):
        out[m.group(1)] = set(re.findall(
            r"^\s*([A-Za-z_]\w*)\s*(?:#\s*\(.*?\)\s*)?[A-Za-z_]\w*\s*(?:\[[^\]]*\]\s*)?\(",
            m.group(2), flags=re.M | re.S))
    return out


def guess_top(files: list[str]) -> tuple[str | None, list[str]]:
    """Among modules no other module instantiates, the one with the largest instance tree;
    testbench-like names last."""
    mods: dict[str, set[str]] = {}
    for f in files:
        if Path(f).suffix in {".vh", ".svh"}:
            continue
        mods.update(_modules(Path(f).read_text(encoding="utf-8", errors="replace")))
    for k in mods:
        mods[k] &= set(mods)
    used = set().union(*mods.values()) if mods else set()

    def tree(m: str, seen: frozenset = frozenset()) -> int:
        if m in seen:
            return 0
        return 1 + sum(tree(c, seen | {m}) for c in mods.get(m, ()))

    cands = [m for m in mods if m not in used]
    tb = re.compile(r"(^tb_?|_tb$|testbench|^test_)", re.I)
    cands.sort(key=lambda m: (bool(tb.search(m)), -tree(m)))
    return (cands[0] if cands else None), cands


def entry_from_dir(rtl: Path, top: str | None) -> dict:
    files = sorted(str(p.resolve()) for p in rtl.rglob("*") if p.suffix in RTL_EXT and p.is_file())
    src = [f for f in files if Path(f).suffix in {".v", ".sv"}]
    incs = sorted({str(Path(f).parent) for f in files})
    if not top:
        top, _ = guess_top(src)
    # testbench files beside the RTL are kept out of elaboration; sim.find_testbench sees them
    tb_like = [f for f in src if re.search(r"(_tb|tb_|testbench)", Path(f).stem, re.I)]
    design = [f for f in src if f not in tb_like] or src
    return {"name": top or rtl.name or "design", "files": design, "top": top, "include_dirs": incs,
            "defines": [], "tb": None, "tb_candidates": tb_like}


def load_entries(a: argparse.Namespace) -> list[dict]:
    if a.rtl:
        p = Path(a.rtl)
        if p.is_file():
            e = {"name": p.stem, "files": [str(p.resolve())], "top": a.top, "include_dirs":
                 [str(p.parent.resolve())], "defines": [], "tb": None}
            if not e["top"]:
                e["top"], _ = guess_top(e["files"])
            out = [e]
        else:
            out = [entry_from_dir(p, a.top)]
    else:
        out = json.loads(Path(a.manifest).read_text())
    for e in out:
        e["files"] = [_abs(f) for f in e["files"]]
        e["include_dirs"] = [_abs(f) for f in e.get("include_dirs") or []]
    if a.only:
        rx = re.compile(a.only)
        out = [e for e in out if rx.search(e["name"])]
    return out


# ------------------------------------------------------------------ stages
class Stages:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def run(self, design: str, stage: str, fn, *args, **kw):
        t0 = time.perf_counter()
        try:
            out = fn(*args, **kw)
            self.rows.append({"design": design, "stage": stage, "ok": True,
                              "seconds": round(time.perf_counter() - t0, 3)})
            return out, None
        except Exception as e:  # noqa: BLE001 - every stage failure is reported, never fatal
            tb = traceback.format_exc(limit=6)
            self.rows.append({"design": design, "stage": stage, "ok": False,
                              "seconds": round(time.perf_counter() - t0, 3),
                              "error": f"{type(e).__name__}: {e}", "trace": tb})
            return None, f"{stage}: {type(e).__name__}: {e}"


def _rel(p: Path | str | None) -> str | None:
    if p is None:
        return None
    p = Path(p).resolve()
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


def _l1(entry: dict, out: Path):
    from rtl2d_l1.pipeline import RunConfig, annotate_design

    cfg = RunConfig(mode="heuristic", targets=frozenset({"block", "fsm", "timing"}))
    return annotate_design(entry["files"], top=entry["top"], include_dirs=entry.get(
        "include_dirs") or None, defines=entry.get("defines") or None, cfg=cfg,
        out_dir=out, name=entry["name"])


def run_fsm(entry: dict, run, d: Path, st: Stages, a: argparse.Namespace, res: dict) -> list:
    name = entry["name"]
    e8 = x4_tools.load(x4_tools.E8 / "e8_extract.py", "e8_extract")
    bridge = x4_tools.x4("fsm_bridge")
    check = x4_tools.x4("fsm_check")
    draw = x4_tools.load(x4_tools.E4 / "fsm_draw.py", "e4_fsm_draw")
    rt = x4_tools.load(x4_tools.E4 / "fsm_roundtrip.py", "e4_fsm_roundtrip")
    ext, err = st.run(name, "e8.enrich", e8.enrich, run, counters=a.counters)
    if err:
        res["errors"].append(err)
        return []
    _dump(d / "fsm_ext.json", ext)
    ext, swapped = semantic_fallback(ext, run) if a.prove else (ext, set())
    graphs, err = st.run(name, "fsm_bridge.build", bridge.build, name, ext)
    if err:
        res["errors"].append(err)
        return []
    vers = x4_tools.versions()
    rows = []
    for g in graphs:
        gid = f"{g.module}.{g.state_reg}"
        sub = d / ("fsm" if g.status == "ok" else "fsm_rejected")
        g.checks.structural = check.structural(g)
        g.provenance.tool_versions = {k: vers.get(k) for k in ("yosys", "sby", "yices-smt2")}
        if g.status == "ok" and not a.no_yosys:
            y, err = st.run(name, "fsm_yosys.check", fsm_yosys_check, entry, g, d / "yosys" / gid)
            g.checks.yosys = y or {"status": "skipped", "error": err}
        if (g.module, g.state_reg) in swapped:
            g.simplifications.append(x4_tools.x4("fsm_spec").Simplification(
                what="graph built from the executed transitions",
                reason="L1's syntactic reading disagreed with execution (semantic_check "
                       "mismatch); the executed graph is kept only if SymbiYosys proves it "
                       "complete, otherwise the FSM is rejected"))
        if g.status == "ok" and a.prove:
            prove = x4_tools.x4("fsm_prove")
            p, err = st.run(name, "fsm_prove.prove", prove.prove, entry, g, d / "formal" / gid,
                            depth=a.depth, timeout=a.prove_timeout)
            g.checks.completeness = p or {"status": "skipped(error)", "error": err}
            if g.checks.completeness.get("status") == "failed(edge)" and not \
                    g.checks.completeness.get("submodule"):
                g = repair_with_proof(entry, g, d, st, a)
            if (g.module, g.state_reg) in swapped and not str(
                    g.checks.completeness.get("status", "")).startswith(("proven", "bounded")):
                g.status = "rejected"
                g.rejected_reason = ("G3+G6: syntactic/executed mismatch and the executed graph "
                                     f"is not proven ({g.checks.completeness.get('status')})")
        elif g.status == "ok":
            g.checks.completeness = {"status": "skipped(not requested)"}
        gd = g.model_dump()
        drawn, err = st.run(name, "e4.fsm_draw", draw.draw, gd, sub / gid)
        svg = None
        if drawn:
            svg = sub / f"{gid}.svg"
            r, err2 = st.run(name, "e4.fsm_roundtrip", rt.check, gd,
                             svg.read_text(encoding="utf-8"))
            g.checks.roundtrip = r or {"ok": False, "error": err2}
        else:
            g.checks.roundtrip = {"ok": False, "error": err}
        _dump(sub / f"{gid}.json", g.model_dump())
        rows.append({
            "id": gid, "svg": _rel(svg), "json": _rel(sub / f"{gid}.json"),
            "mmd": _rel(sub / f"{gid}.mmd") if (sub / f"{gid}.mmd").exists() else None,
            "status": g.status, "rejected_reason": g.rejected_reason,
            "encoding": g.encoding, "states": len(g.states), "transitions": len(g.transitions),
            "engine": g.provenance.engine,
            "checks": g.checks.model_dump(), "simplifications": [
                s.model_dump() for s in g.simplifications],
        })
    res["fsm"] = rows
    return graphs


def _reset_name(f: dict, names: dict[str, str], run) -> str | None:
    """Reset state of an FSM from L1's executing engine (fsm_semantic.analyze), when the
    syntactic reader found none (e.g. `cur <= reset ? R0 : nxt`)."""
    if f.get("reset_state"):
        return f["reset_state"]
    key = (f.get("extra") or {}).get("graph_key")
    if not key or run is None:
        return None
    from rtl2d_l1.frontend.fsm_semantic import analyze

    r = analyze(run.design, run.graph, key, seed=0)
    return names.get(str(r.reset_value)) if r.reset_value is not None else None


def semantic_fallback(ext: list[dict], run=None) -> tuple[list[dict], set]:
    """For FSMs whose syntactic and executed graphs disagree (semantic_check mismatch), use the
    executed transitions (named through e8's value map) instead, marked semantic-only; the
    proof then decides whether the FSM is drawn. Returns (new ext, {(module, state)} swapped)."""
    out, swapped = [], set()
    for f in ext:
        sem = f.get("semantic_transitions") or []
        vals = (f.get("extra") or {}).get("values") or {}
        names = {str(v): k for k, v in vals.items() if v is not None}
        if f.get("semantic_check") != "mismatch" or not sem or not names:
            out.append(f)
            continue
        if any(str(t["src"]) not in names or str(t["dst"]) not in names for t in sem):
            out.append(f)
            continue
        g = dict(f)
        g["transitions"] = [{"src": names[str(t["src"])], "dst": names[str(t["dst"])],
                             "cond": t.get("cond", "<datapath condition>")} for t in sem]
        g["semantic_transitions"] = [[t["src"], t["dst"]] for t in g["transitions"]]
        g["semantic_check"] = "semantic-only"
        g["style"] = "semantic"
        g["reset_state"] = _reset_name(f, names, run)
        g["warnings"] = [*f.get("warnings", []),
                         "x4: syntactic transitions replaced by the executed ones (mismatch)"]
        out.append(g)
        swapped.add((f["module"], f["state"]))
    return out, swapped


def add_proof_edges(g, missing: list[dict]):
    """Return a copy of `g` with the transitions a SymbiYosys counterexample from reset showed
    (each one is reachable: the trace starts at the design's reset). The executed engine samples
    inputs, so an edge whose guard needs a deep counter value can be missed; the proof finds it.
    Transitions out of the same source that claimed to be unconditional are demoted to an
    unknown guard, since another exit exists. Every change is recorded in simplifications."""
    spec = x4_tools.x4("fsm_spec")
    g = g.model_copy(deep=True)
    by_name = {s.name: s.id for s in g.states}
    have = {(t.src, t.dst) for t in g.transitions}
    n = max((int(t.id.split(".")[-1]) for t in g.transitions if t.id.split(".")[-1].isdigit()),
            default=0)
    for m in missing:
        src, dst = by_name.get(m["src"]), by_name.get(m["dst"])
        if src is None or dst is None or (src, dst) in have:
            continue
        n += 1
        g.transitions.append(spec.Transition(
            id=f"t.{n}", src=src, dst=dst, guard="?", guard_kind="unknown", seen_by=["proof"]))
        have.add((src, dst))
        g.simplifications.append(spec.Simplification(
            what=f"added {m['src']} -> {m['dst']}",
            reason=f"SymbiYosys counterexample from reset ({m.get('phase')}): the executed "
                   "engine did not reach this edge; its guard is not derived (drawn as '?')"))
        for t in g.transitions:
            if t.src == src and t.guard_kind == "always":
                t.guard, t.guard_kind = "?", "unknown"
                g.simplifications.append(spec.Simplification(
                    what=f"guard of {t.id} demoted from 1 to '?'",
                    reason=f"{m['src']} has another exit ({m['dst']}), so this transition "
                           "cannot be unconditional"))
    return g


def repair_with_proof(entry: dict, g, d: Path, st: Stages, a: argparse.Namespace):
    """G6 repair loop (one round): add the proof's missing edges, then prove and cross-check the
    repaired graph again. The first proof's result is kept under completeness.before_repair."""
    first = dict(g.checks.completeness)
    g2 = add_proof_edges(g, first.get("missing_edges") or [])
    gid = f"{g.module}.{g.state_reg}"
    prove = x4_tools.x4("fsm_prove")
    p, err = st.run(entry["name"], "fsm_prove.prove#repair", prove.prove, entry, g2,
                    d / "formal" / f"{gid}.repair", depth=a.depth, timeout=a.prove_timeout)
    g2.checks.completeness = dict(p or {"status": "skipped(error)", "error": err})
    g2.checks.completeness["before_repair"] = {
        k: first.get(k) for k in ("status", "missing_edges", "covered", "total")}
    if not a.no_yosys:
        y, err = st.run(entry["name"], "fsm_yosys.check#repair", fsm_yosys_check, entry, g2,
                        d / "yosys" / f"{gid}.repair")
        g2.checks.yosys = y or {"status": "skipped", "error": err}
    return g2


def fsm_yosys_check(entry, g, work):
    return x4_tools.x4("fsm_yosys").check(entry, g, work)


def run_timing(entry: dict, run, d: Path, st: Stages, a: argparse.Namespace, res: dict) -> None:
    name = entry["name"]
    e9 = x4_tools.load(x4_tools.E9 / "e9_select.py", "e9_select")
    sim = x4_tools.x4("sim")
    vcd_mod = x4_tools.x4("vcd")
    tb = x4_tools.x4("timing_bridge")
    tc = x4_tools.x4("timing_check")
    wd = x4_tools.load(x4_tools.E4 / "wave_draw.py", "e4_wave_draw")
    wc = x4_tools.load(x4_tools.E4 / "wave_check.py", "e4_wave_check")
    signals, err = st.run(name, "e9.select", e9.select, run)
    if err:
        res["errors"].append(err)
        return
    _dump(d / "signals.json", signals)
    confirmed = [i for i in signals.get("interfaces", []) if i.get("confirmed")]
    if not confirmed:
        res["notes"].append("timing: no structurally confirmed interface; nothing to draw "
                            f"({len(signals.get('interfaces', []))} candidate(s) demoted)")
        return
    s1, err = st.run(name, "sim.simulate", sim.simulate, entry, signals, d / "sim",
                     simulator=a.sim, seed=a.seed, cycles=a.cycles)
    if err or not s1 or not s1.get("ok"):
        res["errors"].append(err or f"sim: {s1.get('error') if s1 else 'no result'}")
        return
    s2, _ = st.run(name, "sim.simulate#2", sim.simulate, entry, signals, d / "sim_rerun",
                   simulator=s1["simulator"], seed=a.seed, cycles=a.cycles)
    det = {"ok": bool(s2 and s2.get("vcd_sha256") == s1.get("vcd_sha256")),
           "sha256": [s1.get("vcd_sha256"), s2.get("vcd_sha256") if s2 else None],
           "simulator": s1.get("simulator"), "warnings": s1.get("warnings", [])}
    shutil.rmtree(d / "sim_rerun", ignore_errors=True)
    vcd, err = st.run(name, "vcd.parse", vcd_mod.parse, Path(_abs(s1["vcd"])))
    if err:
        res["errors"].append(err)
        return
    graph = run.graph.to_json()
    fsm_ext = None
    if (d / "fsm_ext.json").exists():
        fsm_ext = json.loads((d / "fsm_ext.json").read_text())
    diagrams, err = st.run(name, "timing_bridge.build", tb.build, name, signals, graph, s1, vcd,
                           fsm_ext=fsm_ext)
    if err:
        res["errors"].append(err)
        return
    if not diagrams:
        res["notes"].append("timing: simulation produced no handshake event on any confirmed "
                            "interface (no-window)")
    wcmd = x4_tools.wavedrom_cmd()
    rows = []
    for dg in diagrams:
        chk, err = st.run(name, "timing_check.check", tc.check, dg, vcd, graph, s1, fsm_ext)
        dg.checks.update(chk or {"replay": {"ok": False, "error": err}})
        dg.checks["determinism"] = det
        stem = d / "timing" / dg.id.replace("/", "_")
        dd = dg.model_dump()
        drawn, err = st.run(name, "e4.wave_draw", wd.draw, dd, stem, wavedrom_cmd=wcmd)
        if drawn:
            svg_text = Path(f"{stem}.svg").read_text(encoding="utf-8")
            wj = json.loads(Path(f"{stem}.wavedrom.json").read_text(encoding="utf-8"))
            r, err2 = st.run(name, "e4.wave_check", wc.check, dd, svg_text, wj)
            dg.checks["roundtrip"] = r or {"ok": False, "error": err2}
        else:
            dg.checks["roundtrip"] = {"ok": False, "error": err}
        _dump(Path(f"{stem}.json"), dg.model_dump())
        rows.append({
            "id": dg.id, "svg": _rel(f"{stem}.svg") if drawn else None,
            "json": _rel(f"{stem}.json"),
            "wavedrom": _rel(f"{stem}.wavedrom.json") if drawn else None,
            "interface": dg.interface, "protocol": dg.protocol, "scenario": dg.scenario,
            "lanes": sum(len(dm.lanes) for dm in dg.domains), "arrows": len(dg.arrows),
            "gaps": len(dg.gaps), "domains": len(dg.domains),
            "checks": dg.checks, "simplifications": [s.model_dump() for s in dg.simplifications],
        })
    res["timing"] = rows
    res["sim"] = {k: s1.get(k) for k in ("kind", "simulator", "version", "warnings", "tb_path",
                                         "seed", "vcd_sha256")}


def run_block(entry: dict, d: Path, st: Stages, res: dict) -> None:
    bt = x4_tools.x4("block_tab")
    b, err = st.run(entry["name"], "block_tab.draw_block", bt.draw_block, entry, d / "block")
    if err or not b:
        res["block"] = {"svg": None, "ok": False, "error": err}
    else:
        res["block"] = {"svg": _rel(b.get("svg_path")), "ok": bool(b.get("ok")),
                        "error": b.get("error"), "notes": b.get("notes")}


def one(entry: dict, out: Path, a: argparse.Namespace, st: Stages) -> dict:
    name = entry["name"]
    d = out / "designs" / name
    d.mkdir(parents=True, exist_ok=True)
    parts = set(a.part.split(","))
    res: dict = {"design": name, "top": entry["top"], "files": [_rel(f) for f in entry["files"]],
                 "errors": [], "notes": [], "block": None, "fsm": [], "timing": []}
    t0 = time.perf_counter()
    if not entry.get("top"):
        res["errors"].append("no top module found")
    else:
        run = None
        if parts & {"fsm", "timing"}:
            run, err = st.run(name, "l1.annotate_design", _l1, entry, d / "l1")
            if err:
                res["errors"].append(err)
        if run is not None and "fsm" in parts:
            run_fsm(entry, run, d, st, a, res)
        if run is not None and "timing" in parts:
            run_timing(entry, run, d, st, a, res)
        if "block" in parts:
            run_block(entry, d, st, res)
    res["seconds"] = round(time.perf_counter() - t0, 2)
    _dump(d / "result.json", res)
    return res


def isomorphism(results: list[dict], out: Path) -> dict:
    """G5: an FSM must have the same state graph whatever the coding style (orig/S1/S2)."""
    check = x4_tools.x4("fsm_check")
    spec = x4_tools.x4("fsm_spec")
    groups: dict[str, dict[str, list]] = {}
    for r in results:
        m = VARIANT.match(r["design"])
        if not m:
            continue
        ok = [f for f in r["fsm"] if f["status"] == "ok"]
        groups.setdefault(m.group(2), {})[m.group(1)] = ok
    report = {}
    for base, var in sorted(groups.items()):
        if len(var) < 2:
            continue
        if any(len(v) != 1 for v in var.values()):
            report[base] = {"ok": False, "reason": "FSM count differs per variant: " + ", ".join(
                f"{k}={len(v)}" for k, v in sorted(var.items()))}
            continue
        graphs = {k: spec.FsmGraph.model_validate_json(Path(_abs(v[0]["json"])).read_text())
                  for k, v in var.items()}
        report[base] = check.isomorphic(graphs)
    for r in results:  # write the verdict back into each variant's FSM row
        m = VARIANT.match(r["design"])
        if m and m.group(2) in report:
            for f in r["fsm"]:
                if f["status"] == "ok":
                    f["checks"]["isomorphic"] = report[m.group(2)]
    _dump(out / "isomorphism.json", report)
    return report


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest")
    src.add_argument("--rtl", help="an RTL file or a folder (searched recursively)")
    ap.add_argument("--top")
    ap.add_argument("--only", help="regex over design names")
    ap.add_argument("--part", default="fsm,timing", help="comma list of block,fsm,timing")
    ap.add_argument("--out", default=str(x4_tools.OUT))
    ap.add_argument("--prove", action="store_true", help="G6: SymbiYosys completeness proof")
    ap.add_argument("--depth", type=int, default=20)
    ap.add_argument("--prove-timeout", type=float, default=300.0)
    ap.add_argument("--counters", action="store_true", help="e8: counter-driven FSMs (M4)")
    ap.add_argument("--no-yosys", action="store_true")
    ap.add_argument("--sim", default="auto", choices=["auto", "iverilog", "verilator"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--cycles", type=int, default=400)
    ap.add_argument("--title", default="x4: FSM graphs and timing diagrams")
    a = ap.parse_args(argv)
    x4_tools.export_path()
    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    entries = load_entries(a)
    st = Stages()
    results = []
    for e in entries:
        print(f"[x4] {e['name']} (top {e['top']})", flush=True)
        r = one(e, out, a, st)
        print(f"[x4]   {r['seconds']}s fsm={len(r['fsm'])} timing={len(r['timing'])} "
              f"errors={len(r['errors'])}", flush=True)
        for err in r["errors"]:
            print(f"[x4]   ! {err}", flush=True)
        results.append(r)
    if "fsm" in a.part:
        isomorphism(results, out)
    _dump(out / "results.json", results)
    _dump(out / "stages.json", st.rows)
    _dump(out / "rejected.json", [
        {"design": r["design"], "fsm": f["id"], "reason": f["rejected_reason"]}
        for r in results for f in r["fsm"] if f["status"] != "ok"])
    gallery = x4_tools.x4("gallery")
    page = gallery.build(results, out / "gallery.html", title=a.title)
    print(f"[x4] gallery: {page}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
