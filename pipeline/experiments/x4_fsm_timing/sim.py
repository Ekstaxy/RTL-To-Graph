"""x4 sim: simulate one design with an existing or a generated testbench and record sim.json
(plan §3 Stage 2, FORMATS.md "sim.json").

    uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/sim.py \
        --manifest pipeline/experiments/x4_fsm_timing/manifest_timing.json --name sync_fifo \
        --signals runs/e9_protocol_templates/sync_fifo/signals.json \
        --out runs/x4_fsm_timing/designs/sync_fifo/sim [--simulator auto] [--seed 1] \
        [--cycles 400] [--no-tb]

Writes OUT/{tb_gen.sv, wave.vcd, sim.json, sim.log}. `--simulator auto` runs
`iverilog -g2012` + `vvp` first and falls back to `verilator --binary --timing --trace` when
iverilog fails or prints a `sorry:` line (unsupported construct, i.e. possibly wrong
semantics). All tool calls go through x4_tools.run_capped (memory cap + timeout).

vcd_sha256 is taken over the VCD with its `$date ... $end` block removed (iverilog stamps the
wall clock there), so two runs of the same bench give the same hash.

All times in sim.json (clocks[].period/phase, resets[].release_t, end_t) are in VCD timescale
units, also given as `time_unit` (1ps with the generated bench, whose `timescale is 1ns/1ps).
An existing bench beside the RTL is used first; its clocks and resets are measured on the DUT
ports in its VCD. If none of the signals.json clocks toggles there, or the bench fails or
dumps outside OUT, the generated bench is used and the reason is noted.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MAX_WARN = 60  # warning lines kept verbatim in sim.json; the rest are counted
_SEARCH_SUBDIRS = ("tb", "test", "tests", "bench", "sim", "testbench", "verif")
_TB_NAME = re.compile(r"(_tb|tb|_test)\.s?v$|^(tb_|testbench)\w*\.s?v$", re.I)
_PORTLESS = re.compile(r"\bmodule\s+(\w+)\s*(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?(?:\(\s*\))?\s*;")
_WARN = re.compile(r"sorry:|%Warning|\bwarning:", re.I)
MAX_CANDIDATES = 20  # rejected bench candidates kept in sim.json (the rest are counted)
_VERSION_CACHE: dict[str, str | None] = {}


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _tools():
    """x4_tools is this experiment's own helper (loaded by file, like x4_tools.x4 does)."""
    return _load("x4_tools")


def _tbgen():
    return _tools().x4("tbgen")


def _rel(p: Path | str) -> str:
    q = Path(p).resolve()
    try:
        return str(q.relative_to(ROOT))
    except ValueError:
        return str(q)


def _resolve(p: str | Path) -> Path:
    q = Path(p)
    return q if q.is_absolute() else ROOT / q


# ---------------------------------------------------------------- existing testbench search


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def _instance_of(text: str, top: str) -> str | None:
    """Instance name of the first `top [#(...)] name [dims] (` in text. Module headers are
    blanked first, and the top name must be a whole identifier, so `module top_tb();` or
    `module top();` never count as instances."""
    body = re.sub(r"\b(?:module|macromodule|program|interface)\s+[\w$]+", " ", text)
    m = re.search(rf"(?<![\w$.]){re.escape(top)}(?![\w$])\s*"
                  rf"(?:#\s*\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)\s*)?"
                  rf"([A-Za-z_][\w$]*)\s*(?:\[[^\]]*\]\s*)*\(", body)
    return m.group(1) if m else None


def _judge(path: Path, top: str) -> dict:
    """One candidate file -> {path, accepted, reason, tb_top, dut_inst, dumpfile}."""
    try:
        raw = path.read_text(errors="replace")
    except OSError as e:
        return {"path": _rel(path), "accepted": False, "reason": f"unreadable: {e}"}
    text = _strip_comments(raw)
    out = {"path": _rel(path), "accepted": False, "reason": "", "tb_top": None,
           "dut_inst": None, "dumpfile": None}
    inst = _instance_of(text, top)
    portless = [m.group(1) for m in _PORTLESS.finditer(text)]
    if inst is None:
        out["reason"] = f"does not instantiate {top}"
    elif not portless:
        out["reason"] = "no portless module (not a top-level bench)"
    elif re.search(r"\$readmem[hb]", text):
        out["reason"] = "uses $readmemh/$readmemb (needs firmware or a hex file)"
    elif re.search(r"cocotb", raw, re.I) or (path.parent / "Makefile").is_file() and re.search(
            r"cocotb", (path.parent / "Makefile").read_text(errors="replace"), re.I):
        out["reason"] = "cocotb bench (needs a Python runner)"
    else:
        out.update(accepted=True, reason="portless module instantiating the top",
                   tb_top=portless[0], dut_inst=inst)
        m = re.search(r"\$dumpfile\s*\(\s*\"([^\"]+)\"", text)
        out["dumpfile"] = m.group(1) if m else None
    return out


def scan_testbenches(entry: dict, *, limit: int = 300) -> dict:
    """Look beside the RTL (and in tb/test/bench/sim siblings) for a bench of the top.
    Returns {chosen: candidate | None, candidates: [...], unscanned, unscanned_total} with a
    reason for every rejection. Bench-named files (*_tb.sv, tb_*.v, testbench*.v, ...) are
    judged first; at most `limit` files are read and the rest are listed as unscanned."""
    if entry.get("tb"):
        c = _judge(_resolve(entry["tb"]), entry["top"])
        c["reason"] = "given by the entry; " + c["reason"]
        return {"chosen": c if c["accepted"] else None, "candidates": [c], "unscanned": [],
                "unscanned_total": 0}
    own = {_resolve(f).resolve() for f in entry["files"]}
    dirs: list[Path] = []
    for f in entry["files"]:
        d = _resolve(f).resolve().parent
        for c in [d, *[d / s for s in _SEARCH_SUBDIRS], *[d.parent / s for s in _SEARCH_SUBDIRS]]:
            if c.is_dir() and c not in dirs:
                dirs.append(c)
    found = sorted({p.resolve() for d in dirs for p in (*d.glob("*.v"), *d.glob("*.sv"))}
                   - own, key=lambda p: (not _TB_NAME.search(p.name), str(p)))
    files, unscanned = found[:limit], found[limit:]
    cands = []
    for p in files:
        c = _judge(p, entry["top"])
        if c["accepted"] or _TB_NAME.search(p.name) or c["reason"] != (
                f"does not instantiate {entry['top']}"):
            cands.append(c)
    ok = [c for c in cands if c["accepted"]]
    ok.sort(key=lambda c: (not _TB_NAME.search(Path(c["path"]).name), len(c["path"]), c["path"]))
    return {"chosen": ok[0] if ok else None, "candidates": cands,
            "unscanned": [_rel(p) for p in unscanned[:MAX_CANDIDATES]],
            "unscanned_total": len(unscanned)}


def find_testbench(entry: dict) -> Path | None:
    """Existing bench beside the RTL (*_tb.sv, *tb.v, testbench*.v or any portless module
    instantiating the top), rejecting $readmemh firmware and cocotb benches. The reasons are
    in scan_testbenches(entry)["candidates"]."""
    c = scan_testbenches(entry)["chosen"]
    return _resolve(c["path"]) if c else None


# ---------------------------------------------------------------- VCD helpers


def vcd_sha256(path: Path) -> str:
    """sha256 of the VCD without its `$date ... $end` block (wall-clock stamp)."""
    data = Path(path).read_bytes()
    data = re.sub(rb"\$date\b.*?\$end", b"$date $end", data, count=1, flags=re.S)
    return hashlib.sha256(data).hexdigest()


def vcd_timescale(path: Path) -> str | None:
    with open(path, "rb") as fh:
        head = fh.read(1 << 16).decode(errors="replace")
    m = re.search(r"\$timescale\s+(.*?)\s*\$end", head, re.S)
    return re.sub(r"\s+", "", m.group(1)) if m else None


def _unit_ns(ts: str | None) -> float | None:
    m = re.fullmatch(r"(1|10|100)(s|ms|us|ns|ps|fs)", ts or "")
    if not m:
        return None
    mult = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1.0, "ps": 1e-3, "fs": 1e-6}[m.group(2)]
    return int(m.group(1)) * mult


# ---------------------------------------------------------------- simulators


def _version(tool: str) -> str | None:
    if tool not in _VERSION_CACHE:
        t = _tools()
        exe = t.which(tool)
        arg = "-V" if tool == "iverilog" else "--version"
        if exe is None:
            _VERSION_CACHE[tool] = None
        else:
            r = t.run_capped([exe, arg], timeout=30, mem="10%")
            lines = (r.stdout or r.stderr).strip().splitlines()
            _VERSION_CACHE[tool] = lines[0] if lines else None
    return _VERSION_CACHE[tool]


def _flags(entry: dict, inc: str, dfn: str) -> list[str]:
    out = []
    for d in entry.get("include_dirs") or []:
        out.append(f"{inc}{_resolve(d)}")
    for d in entry.get("defines") or []:
        out.append(f"{dfn}{d}")
    return out


def _warnings(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if _WARN.search(ln)]


def _step(log: list[str], cmd: list[str], r) -> str:
    out = (r.stdout or "") + (r.stderr or "")
    log.append(f"$ {' '.join(cmd)}\n[exit {r.returncode}]\n{out}")
    return out


def run_iverilog(entry: dict, srcs: list[Path], top: str, out_dir: Path, log: list[str],
                 *, timeout: float = 300.0) -> dict:
    t = _tools()
    exe, vvp = t.which("iverilog"), t.which("vvp")
    if not exe or not vvp:
        return {"ok": False, "error": "iverilog/vvp not found", "cmd": [], "warnings": []}
    files = [str(_resolve(f)) for f in entry["files"]]
    c1 = [exe, "-g2012", "-o", "a.out", "-s", top, *_flags(entry, "-I", "-D"),
          *[str(s) for s in srcs], *files]
    r1 = t.run_capped(c1, cwd=out_dir, timeout=180, mem="25%")
    o1 = _step(log, c1, r1)
    res = {"cmd": [c1], "warnings": _warnings(o1), "ok": False, "error": None}
    if r1.returncode != 0:
        res["error"] = f"iverilog exit {r1.returncode}: " + _first_err(o1)
        return res
    c2 = [vvp, "-n", "a.out"]
    r2 = t.run_capped(c2, cwd=out_dir, timeout=timeout, mem="25%")
    o2 = _step(log, c2, r2)
    res["cmd"].append(c2)
    res["warnings"] += _warnings(o2)
    res["ok"] = r2.returncode == 0
    res["error"] = None if res["ok"] else f"vvp exit {r2.returncode}: " + _first_err(o2)
    return res


def run_verilator(entry: dict, srcs: list[Path], top: str, out_dir: Path, log: list[str],
                  *, timeout: float = 300.0) -> dict:
    t = _tools()
    exe = t.which("verilator")
    if not exe:
        return {"ok": False, "error": "verilator not found", "cmd": [], "warnings": []}
    files = [str(_resolve(f)) for f in entry["files"]]
    c1 = [exe, "--binary", "--timing", "--trace", "-Wno-fatal", "--top-module", top,
          "--timescale", "1ns/1ps", "--Mdir", "obj_dir", "-o", "Vtb", "--build-jobs", "2",
          *_flags(entry, "-I", "-D"), *[str(s) for s in srcs], *files]
    r1 = t.run_capped(c1, cwd=out_dir, timeout=180, mem="40%")
    o1 = _step(log, c1, r1)
    res = {"cmd": [c1], "warnings": _warnings(o1), "ok": False, "error": None}
    binary = out_dir / "obj_dir" / "Vtb"
    if r1.returncode != 0 or not binary.is_file():
        res["error"] = f"verilator exit {r1.returncode}: " + _first_err(o1)
        return res
    c2 = [str(binary)]
    r2 = t.run_capped(c2, cwd=out_dir, timeout=timeout, mem="25%")
    o2 = _step(log, c2, r2)
    res["cmd"].append(c2)
    res["warnings"] += _warnings(o2)
    res["ok"] = r2.returncode == 0
    res["error"] = None if res["ok"] else f"Vtb exit {r2.returncode}: " + _first_err(o2)
    return res


def _first_err(text: str) -> str:
    for ln in text.splitlines():
        if re.search(r"error|TIMEOUT|sorry", ln, re.I):
            return ln.strip()[:300]
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1][:300] if lines else "no output"


def _sorry(ws: list[str]) -> list[str]:
    return [w for w in ws if "sorry:" in w]


def _run(entry: dict, srcs: list[Path], top: str, out_dir: Path, simulator: str,
         log: list[str], vcd: Path) -> tuple[str, dict, dict | None]:
    """Returns (simulator used, its result, fallback record or None). In auto mode a
    `sorry:` from iverilog switches to Verilator; if Verilator then fails, the iverilog run
    (and its VCD, parked as wave.iverilog.vcd meanwhile) is kept and the fallback says so."""
    vcd.unlink(missing_ok=True)
    if simulator == "verilator":
        return "verilator", run_verilator(entry, srcs, top, out_dir, log), None
    iv = run_iverilog(entry, srcs, top, out_dir, log)
    sorry = _sorry(iv["warnings"])
    if simulator == "iverilog" or (iv["ok"] and not sorry):
        return "iverilog", iv, None
    fb = {"from": "iverilog", "reason": iv["error"] or "sorry: lines", "sorry": sorry[:MAX_WARN]}
    park = out_dir / "wave.iverilog.vcd"
    parked = bool(iv["ok"] and vcd.is_file())
    if parked:
        vcd.replace(park)
    vl = run_verilator(entry, srcs, top, out_dir, log)
    if vl["ok"] or not parked:
        park.unlink(missing_ok=True)
        return "verilator", vl, fb
    vcd.unlink(missing_ok=True)
    park.replace(vcd)
    fb.update(kept="iverilog", verilator_error=vl["error"], verilator_cmd=vl["cmd"])
    log.append(f"# verilator failed ({vl['error']}); iverilog run with sorry: lines kept")
    return "iverilog", iv, fb


# ---------------------------------------------------------------- VCD edge scan


def _vcd_tokens(path: Path):
    with open(path, errors="replace") as fh:
        for line in fh:
            yield from line.split()


def _vcd_changes(path: Path, names: set[str]) -> dict[str, list[tuple[int, str]]]:
    """Value changes [(t, value)] of the named VCD variables (full dotted scope names), read
    as a stream so a large bench VCD is never held in memory."""
    toks = _vcd_tokens(path)
    codes: dict[str, list[str]] = {}
    stack: list[str] = []
    for tok in toks:
        if tok == "$enddefinitions":
            break
        if tok not in ("$scope", "$upscope", "$var"):
            continue
        body = []
        for b in toks:
            if b == "$end":
                break
            body.append(b)
        if tok == "$scope" and len(body) >= 2:
            stack.append(body[1])
        elif tok == "$upscope" and stack:
            stack.pop()
        elif tok == "$var" and len(body) >= 4:
            name = ".".join([*stack, body[3].lstrip("\\")])
            if name in names:
                codes.setdefault(body[2], []).append(name)
    out: dict[str, list[tuple[int, str]]] = {n: [] for c in codes.values() for n in c}
    t, pending = 0, None
    for tok in toks:
        if pending is not None:
            for n in codes.get(tok, ()):
                out[n].append((t, pending))
            pending = None
        elif tok[0] == "#":
            t = int(tok[1:])
        elif tok[0] in "bBrR":
            pending = tok[1:]
        elif tok[0] in "01xXzZ" and len(tok) > 1:
            for n in codes.get(tok[1:], ()):
                out[n].append((t, tok[0].lower()))
    return out


def _posedges(ch: list[tuple[int, str]]) -> list[int]:
    out, prev = [], None
    for t, v in ch:
        if prev is not None and prev != "1" and v == "1":
            out.append(t)
        prev = v
    return out


def _derive_clock(c: dict, ch: list[tuple[int, str]] | None, name: str,
                  notes: list[dict]) -> dict | None:
    edges = _posedges(ch or [])
    if len(edges) < 2:
        notes.append({"what": f"clock {c['port']}", "reason": f"{len(edges)} posedge(s) of "
                      f"{name} in the bench VCD; domain left out", "line": None})
        return None
    deltas = Counter(b - a for a, b in itertools.pairwise(edges))
    period = min(deltas, key=lambda d: (-deltas[d], d))
    if len(deltas) > 1:
        notes.append({"what": f"clock {c['port']}", "reason": f"irregular period in the bench "
                      f"VCD ({len(deltas)} distinct posedge spacings); most common {period} "
                      "used", "line": None})
    return {"port": c["port"], "domain": c["domain"], "period": period, "phase": edges[0],
            "edge": c.get("edge", "posedge")}


def _derive_reset(r: dict, ch: list[tuple[int, str]] | None, name: str,
                  notes: list[dict]) -> dict:
    act = "0" if r["active_low"] else "1"
    seen, rel = False, None
    for t, v in ch or []:
        if v[-1:] == act:
            seen, rel = True, None
        elif seen and rel is None and v[-1:] in "01":
            rel = t
    if rel is None:
        why = (f"{name} not in the bench VCD" if ch is None else
               "still asserted at the end" if seen else "never asserted")
        notes.append({"what": f"reset {r['port']}", "reason": f"release time unknown ({why}); "
                      "release_t null", "line": None})
    return {"port": r["port"], "active_low": r["active_low"], "release_t": rel}


def _bench_timing(vcd: Path, dut_path: str, gen: dict) -> tuple[list, list, list[dict]]:
    """Clocks and resets of an existing-bench run, measured on the DUT ports in the VCD (the
    clock/reset ports come from signals.json via the generated plan). Times in VCD units."""
    cks = [c for c in gen["clocks"] if c.get("port")]
    names = {f"{dut_path}.{x['port']}" for x in (*cks, *gen["resets"])}
    ch = _vcd_changes(vcd, names)
    notes: list[dict] = []
    clocks = [c for c in (_derive_clock(c, ch.get(f"{dut_path}.{c['port']}"),
                                        f"{dut_path}.{c['port']}", notes) for c in cks) if c]
    resets = [_derive_reset(r, ch.get(f"{dut_path}.{r['port']}"), f"{dut_path}.{r['port']}",
                            notes) for r in gen["resets"]]
    if clocks:
        notes.append({"what": "clocks/resets", "reason": "existing bench: clock period/phase "
                      "and reset release measured on the DUT ports in the VCD (VCD units)",
                      "line": None})
    return clocks, resets, notes


# ---------------------------------------------------------------- existing-bench wrapper


def _wrap_existing(c: dict, out_dir: Path, *, dump: str) -> tuple[Path, str]:
    """Wrapper top `x4_wrap` with the bench instantiated as `tb` and a full VCD dump into
    `dump` (the bench's own dumpfile name when it has one: a simulator keeps one dump file,
    so both $dumpvars calls then land in the same file)."""
    body = (f'  initial begin\n    $dumpfile("{dump}");\n    $dumpvars(0, x4_wrap);\n  end\n'
            if dump else "")
    text = (f"// x4 sim: wrapper around the existing bench {c['path']}\n`timescale 1ns/1ps\n"
            f"module x4_wrap;\n  {c['tb_top']} tb();\n{body}endmodule\n")
    p = out_dir / "tb_wrap.sv"
    p.write_text(text, encoding="utf-8")
    return p, "x4_wrap"


def _inside(p: Path, d: Path) -> bool:
    try:
        Path(p).resolve().relative_to(Path(d).resolve())
        return True
    except ValueError:
        return False


def _vcd_end(path: Path) -> int | None:
    """Last timestamp of a VCD (read from the tail)."""
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        fh.seek(max(0, fh.tell() - (1 << 16)))
        stamps = re.findall(rb"^#(\d+)", fh.read(), re.M)
    return int(stamps[-1]) if stamps else None


def _simulate_existing(entry: dict, c: dict, gen: dict, out_dir: Path, simulator: str,
                       log: list[str]) -> tuple[dict | None, str | None]:
    """Run an existing bench. Returns (run, None) or (None, reason it was abandoned).
    A bench with its own $dumpfile runs unwrapped first (hierarchical names stay valid); if it
    writes no VCD (e.g. the dump is behind a plusarg) or no signals.json clock toggles under
    the DUT in it, it is re-run inside `x4_wrap`, which dumps everything to wave.vcd. A bench
    whose $dumpfile points outside out_dir is not run at all."""
    if c["dumpfile"] and not _inside(out_dir / c["dumpfile"], out_dir):
        reason = (f"existing bench dumps to {c['dumpfile']!r}, outside the output directory; "
                  "not run (it would write or replace a file there)")
        log.append(f"# {reason}; falling back to the generated bench")
        return None, reason
    modes = ["direct", "wrapped"] if c["dumpfile"] else ["wrapped"]
    reasons: list[str] = []
    for mode in modes:
        if mode == "direct":
            srcs, top, vcd = [_resolve(c["path"])], c["tb_top"], out_dir / c["dumpfile"]
            tb_top = c["tb_top"]
        else:
            dump = c["dumpfile"] or "wave.vcd"
            wrap, top = _wrap_existing(c, out_dir, dump=dump)
            srcs, vcd, tb_top = [wrap, _resolve(c["path"])], out_dir / dump, "x4_wrap.tb"
        used, res, fb = _run(entry, srcs, top, out_dir, simulator, log, vcd)
        if not res["ok"]:
            reasons.append(f"existing bench failed ({mode}): {res.get('error')}")
            continue
        if not vcd.is_file():
            reasons.append(f"existing bench wrote no VCD ({mode}, {vcd.name})")
            continue
        dut_path = f"{tb_top}.{c['dut_inst']}"
        clocks, resets, tnotes = _bench_timing(vcd, dut_path, gen)
        if not clocks:
            reasons.append(f"existing bench ({mode}): no signals.json clock toggles under "
                           f"{dut_path} in its VCD ({'; '.join(n['reason'] for n in tnotes)})")
            continue
        if vcd.name != "wave.vcd":
            vcd.replace(out_dir / "wave.vcd")
        notes = tnotes
        if mode == "direct":
            notes.append({"what": "VCD", "reason": f"dumped by the bench itself "
                          f"({c['dumpfile']}), with the scopes the bench chose", "line": None})
        return {"kind": "tb", "tb_path": c["path"], "tb_top": tb_top, "dut_path": dut_path,
                "seed": None, "used": used, "res": res, "fb": fb, "clocks": clocks,
                "resets": resets, "end_t": _vcd_end(out_dir / "wave.vcd"), "notes": notes}, None
    reason = "; then ".join(reasons)
    log.append(f"# {reason}; falling back to the generated bench")
    return None, reason


# ---------------------------------------------------------------- main entry


def simulate(entry: dict, signals: dict, out_dir: Path, *, simulator: str = "auto",
             seed: int = 1, cycles: int = 400, use_tb: bool = True) -> dict:
    """Write out_dir/{tb_gen.sv, wave.vcd, sim.json, sim.log}; return the sim.json dict
    (FORMATS.md keys plus `time_unit`, `notes`, `handshakes`, `params`, `fallback`,
    `tb_search`, `semantic_warnings`, `warnings_total`). All times in sim.json (clock
    period/phase, reset release_t, end_t) are in VCD timescale units (`time_unit`, 1ps with
    the generated bench). A failure (e.g. slang cannot read the RTL) still writes sim.json
    with ok=false and the error."""
    if simulator not in ("auto", "iverilog", "verilator"):
        raise ValueError(f"simulator must be auto|iverilog|verilator, not {simulator}")
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    try:
        gen = _tbgen().generate(signals, entry, out_dir, cycles=cycles, seed=seed)
    except Exception as e:  # recorded in sim.json, never lost
        log.append(f"# tbgen.generate failed: {type(e).__name__}: {e}")
        return _write(out_dir, log, _failed(seed, f"tbgen: {type(e).__name__}: {e}"))
    search = scan_testbenches(entry) if use_tb else {"chosen": None, "candidates": [],
                                                     "unscanned": [], "unscanned_total": 0}
    run, why = None, None
    if search["chosen"]:
        run, why = _simulate_existing(entry, search["chosen"], gen, out_dir, simulator, log)
    if run is None:
        used, res, fb = _run(entry, [Path("tb_gen.sv")], gen["tb_top"], out_dir, simulator,
                             log, out_dir / "wave.vcd")
        run = {"kind": "generated", "tb_path": _rel(gen["tb_path"]), "tb_top": gen["tb_top"],
               "dut_path": gen["dut_path"], "seed": seed, "used": used, "res": res, "fb": fb,
               "clocks": gen["clocks"], "resets": gen["resets"], "end_t": gen["end_t"],
               "notes": list(gen["notes"])}
        if why:
            run["notes"].append({"what": f"existing bench {search['chosen']['path']}",
                                 "reason": f"{why}; generated bench used", "line": None})
    if search.get("unscanned_total"):
        run["notes"].append({"what": "testbench search", "reason": f"{search['unscanned_total']}"
                             " files beside the RTL not read (scan limit); listed in "
                             "tb_search.unscanned", "line": None})
    return _write(out_dir, log, _record(run, gen, search, out_dir))


def _write(out_dir: Path, log: list[str], sim: dict) -> dict:
    (out_dir / "sim.log").write_text("\n".join(log), encoding="utf-8")
    (out_dir / "sim.json").write_text(json.dumps(sim, indent=1), encoding="utf-8")
    return sim


def _failed(seed: int, error: str) -> dict:
    """sim.json of a run that never reached a simulator (every key present, ok=false)."""
    return {"kind": "generated", "tb_path": None, "tb_top": None, "dut_path": None,
            "seed": seed, "simulator": None, "version": None, "cmd": [], "warnings": [],
            "vcd": None, "vcd_sha256": None, "timescale": None, "time_unit": None,
            "clocks": [], "resets": [], "end_t": None, "ok": False, "error": error,
            "warnings_total": 0, "semantic_warnings": [], "fallback": None,
            "notes": [{"what": "simulation", "reason": f"not run: {error}", "line": None}],
            "handshakes": [], "params": {}, "tb_search": None}


def _record(run: dict, gen: dict, search: dict, out_dir: Path) -> dict:
    res, fb = run["res"], run["fb"]
    vcd = out_dir / "wave.vcd"
    ok = bool(res["ok"]) and vcd.is_file() and vcd.stat().st_size > 0
    ts = vcd_timescale(vcd) if ok else None
    clocks, resets, end_t = run["clocks"], run["resets"], run["end_t"]
    notes = list(run["notes"])
    unit = _unit_ns(ts)
    if ok and unit and unit != 1.0 and run["kind"] != "tb":
        k = 1.0 / unit
        clocks = [dict(c, period=round(c["period"] * k), phase=round(c["phase"] * k))
                  for c in clocks]
        resets = [dict(r, release_t=round(r["release_t"] * k)) for r in resets]
        end_t = round(end_t * k) if end_t is not None else None
        notes.append({"what": "time unit", "reason": f"VCD timescale is {ts}; clock, reset "
                      "and end times rescaled from 1ns TB units to VCD units", "line": None})
    if fb and fb.get("kept") == "iverilog":
        notes.append({"what": "simulator", "reason": "iverilog printed sorry: lines (see "
                      "semantic_warnings) and the Verilator retry failed "
                      f"({fb['verilator_error']}); the iverilog run is kept", "line": None})
    warns = res["warnings"]
    return {
        "kind": run["kind"], "tb_path": run["tb_path"], "tb_top": run["tb_top"],
        "dut_path": run["dut_path"], "seed": run["seed"], "simulator": run["used"],
        "version": _version(run["used"]), "cmd": res["cmd"],
        "warnings": warns[:MAX_WARN] + ([f"... {len(warns) - MAX_WARN} more"]
                                        if len(warns) > MAX_WARN else []),
        "vcd": _rel(vcd) if ok else None, "vcd_sha256": vcd_sha256(vcd) if ok else None,
        "timescale": ts, "time_unit": ts, "clocks": clocks, "resets": resets, "end_t": end_t,
        "ok": ok, "error": None if ok else (res.get("error") or "no VCD written"),
        "warnings_total": len(warns), "semantic_warnings": _sorry(warns),
        "fallback": fb, "notes": notes, "handshakes": gen["handshakes"],
        "params": gen["params"],
        "tb_search": {"chosen": (search["chosen"] or {}).get("path"),
                      "candidates": search["candidates"][:MAX_CANDIDATES],
                      "candidates_total": len(search["candidates"]),
                      "unscanned": search.get("unscanned", []),
                      "unscanned_total": search.get("unscanned_total", 0)},
    }


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--signals", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--simulator", default="auto", choices=["auto", "iverilog", "verilator"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--cycles", type=int, default=400)
    ap.add_argument("--no-tb", action="store_true", help="skip the existing-bench search")
    a = ap.parse_args(argv)
    man = json.loads(Path(a.manifest).read_text())
    entry = next(e for e in man if e["name"] == a.name)
    sig = json.loads(Path(a.signals).read_text())
    sim = simulate(entry, sig, Path(a.out), simulator=a.simulator, seed=a.seed,
                   cycles=a.cycles, use_tb=not a.no_tb)
    print(json.dumps({k: sim[k] for k in ("kind", "simulator", "ok", "error", "vcd_sha256",
                                          "timescale", "warnings_total")}, indent=1))
    return 0 if sim["ok"] else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
