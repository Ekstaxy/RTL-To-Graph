"""x4 G6: transition completeness of an FsmGraph proved with SymbiYosys (smtbmc yices).

    uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/fsm_prove.py \
        ENTRY.json FSMGRAPH.json WORKDIR [--depth 20] [--timeout 300]

The RTL is copied into WORKDIR/iter<k>/src/ and an `ifdef X4_FORMAL monitor is text-injected before
the `endmodule` of the FSM's module (which is also the sby top, so FSMs in submodules are proved
at instance level with unconstrained inputs):
  * x4_prev = state one clock earlier, x4_pv past-valid, x4_prst = reset active one clock earlier;
  * assume(reset active) in the first cycle; afterwards reset is free and every cycle in which
    reset is active now or was active one clock earlier is not checked (that is the reset
    transition, drawn as the entry arrow);
  * assert state in the set of state values, and assert (x4_prev -> state) is a self-loop (holding
    the state is implicit) or a transition of the graph;
  * one cover per non-self transition (cover task, assertions removed with chformal).
`.sby`: [tasks] prove cover deep; prove: mode prove depth D; cover: mode cover depth D; deep:
mode bmc depth D*10; sby `timeout` = the remaining budget; engine smtbmc yices; -I for the
entry include_dirs and every source file's directory; read -sv -DX4_FORMAL (not -formal:
the design's own `ifdef FORMAL properties, e.g. picorv32's, would otherwise join the proof and
break induction); prep -top MODULE; designs clocked on both edges get `multiclock on`. For a
submodule FSM the parameter overrides along the instance path that resolve to integer literals
are applied with chparam (`params`); anything else keeps the module default and is listed in
`params.unresolved`.
Results: prove PASS -> proven; basecase passes to D but induction does not close -> one BMC
pass at D*DEEP_FACTOR (`deep`, at most DEEP_SHARE of the remaining budget; counter-gated edges
such as traffic_light's 60-tick countdown lie deeper than 20): no violation -> bounded(D*10),
otherwise its counterexamples are missing edges. FAIL -> the counterexample (trace.vcd, last
step) gives the observed (src, dst), which is added to the allowed set and the run repeated
(up to MAX_ITER) to collect every missing edge (`phase` prove | bmc(N)).
`failed(edge)` for top-level FSMs; for an FSM in a submodule an edge that is not a semantic
(executed) transition is re-tried as a cover from the real top (`top_cover`): reached ->
`failed(edge)`; not reached -> a proof at the real top that it never occurs (`top_proof`):
proven -> `failed(unconstrained)` (needs inputs the parent never drives), basecase FAIL ->
`failed(edge)`, unknown -> stays `failed(unconstrained)` with `top_proof` "unknown" (could also
be deeper than D). Covers run at D, the uncovered ones again at D*10 (`cover_deep`,
`cover_depth`); still uncovered ones are then proved absent (`uncovered_check`:
proven_unreachable / reachable / unknown). covered + len(uncovered) == total always; a cover
pass that cannot run is `cover_status` skipped(...).
Deviations from the plan text the integrator acts on: the read is `read -sv -DX4_FORMAL`, not
`read -formal`; failed(edge) of a top-level FSM rests on an sby counterexample from reset (not
on a semantic-engine replay); missing edges are never added to the FsmGraph (they are listed in
`missing_edges`, and `with_missing_added` is the result after allowing them).
No state values -> skipped(no-values); no reset port found -> skipped(no-reset); a frontend
error -> skipped(frontend).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _sibling(name: str):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


x4_tools = _sibling("x4_tools")
fsm_spec = x4_tools.x4("fsm_spec")

MAX_ITER = 8
SOLVER = "smtbmc yices"
DEEP_FACTOR = 10  # bounded / uncovered: one BMC (cover) pass at depth * DEEP_FACTOR
DEEP_SHARE = 0.5  # ... using at most this share of the remaining time budget
_RST = re.compile(r"(?i)^(i_|in_)?(a|s|n)?(rst|reset)(_?n|_b|_ni|_i|_l|_ri)?$")
_RST_LOW = re.compile(r"(?i)(^(i_|in_)?n(rst|reset))|((rst|reset)(_?n|_b|_ni|_l))$")
_CLK = re.compile(r"(?i)^(i_)?(clk|clock|ck|clk_i|aclk)(_i)?$")
_KW = {"input", "output", "inout", "wire", "logic", "reg", "bit", "signed", "unsigned", "var",
       "integer", "int", "tri"}


# ------------------------------------------------------------------ RTL text helpers


def _abs(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else x4_tools.ROOT / q


def mask_comments(text: str) -> str:
    """Comments replaced by spaces (offsets preserved, newlines kept)."""
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    return re.sub(r"//[^\n]*|/\*.*?\*/", blank, text, flags=re.S)


def find_module(texts: dict[str, str], name: str):
    """(file, start, endmodule offset) of `module name` in the comment-masked texts."""
    for f, t in texts.items():
        m = re.search(rf"\b(module|macromodule)\s+{re.escape(name)}\b", t)
        if not m:
            continue
        e = re.search(r"\bendmodule\b", t[m.end():])
        if e:
            return f, m.start(), m.end() + e.start()
    return None


def _mod_text(texts, name) -> str:
    loc = find_module(texts, name)
    return texts[loc[0]][loc[1]:loc[2]] if loc else ""


def input_ports(mtext: str) -> list[str]:
    out = []
    for m in re.finditer(r"\binput\b(.*?)(?=[;)]|\b(?:input|output|inout)\b)", mtext, re.S):
        body = re.sub(r"\[[^\]]*\]", " ", m.group(1))
        for tok in body.split(","):
            words = [w for w in re.findall(r"[A-Za-z_]\w*", tok) if w not in _KW]
            if words:
                out.append(words[-1])
    return list(dict.fromkeys(out))


def _sens(mtext: str) -> list[list[tuple[str, str]]]:
    lists = []
    for m in re.finditer(r"@\s*\(([^)]*)\)", mtext):
        items = re.findall(r"\b(posedge|negedge)\s+([A-Za-z_]\w*)", m.group(1))
        if items:
            lists.append(items)
    return lists


def find_clock(mtext: str, reset: str | None) -> str | None:
    counts: dict[str, int] = {}
    for items in _sens(mtext):
        e, n = items[0]
        if e == "posedge" and n != reset:
            counts[n] = counts.get(n, 0) + 1
    if counts:
        return max(sorted(counts), key=lambda n: counts[n])
    clk = [p for p in input_ports(mtext) if _CLK.match(p)]
    return clk[0] if clk else None


def _polarity_from_text(mtext: str, port: str) -> bool | None:
    p = re.escape(port)
    if re.search(rf"if\s*\(\s*[!~]\s*{p}\s*\)|{p}\s*==\s*1'b0", mtext):
        return True
    if re.search(rf"if\s*\(\s*{p}\s*\)|{p}\s*==\s*1'b1", mtext):
        return False
    return None


def module_reset(mtext: str) -> dict | None:
    """Reset of one module from its own text: async sensitivity entry, else a name hint."""
    asyn = [(e, n) for items in _sens(mtext) for e, n in items[1:]]
    asyn.sort(key=lambda x: _RST.match(x[1]) is None)  # stable: name-hinted async first
    if asyn:
        e, n = asyn[0]
        return {"port": n, "active_low": e == "negedge", "how": "async sensitivity"}
    for p in input_ports(mtext):
        if _RST.match(p):
            pol = _polarity_from_text(mtext, p)
            low = bool(_RST_LOW.search(p)) if pol is None else pol
            return {"port": p, "active_low": low, "how": "name hint"}
    return None


_CONN = re.compile(r"\.\s*([A-Za-z_]\w*)\s*\(((?:[^()]|\([^()]*\))*)\)")
_LIT = re.compile(r"\d+|\d*'[sS]?[bBoOdDhH][0-9a-fA-F_]+")


def _instance(texts, parent: str, inst: str, params: bool = False):
    """(child module, {port: expr}) of instance `inst` inside module `parent`; with
    `params=True` the {parameter: expr} overrides of its `#( .P(expr) )` list instead."""
    body = _mod_text(texts, parent)
    m = re.search(rf"\b([A-Za-z_]\w*)\s*(?:#\s*(\((?:[^()]|\([^()]*\))*\))\s*)?"
                  rf"{re.escape(inst)}\s*\(", body)
    if not m:
        return None, {}
    if params:
        return m.group(1), {p: e.strip() for p, e in _CONN.findall(m.group(2) or "")}
    depth, i = 1, m.end()
    while i < len(body) and depth:
        depth += (body[i] == "(") - (body[i] == ")")
        i += 1
    return m.group(1), {p: e.strip() for p, e in _CONN.findall(body[m.end():i])}


def _param_defaults(mtext: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r"\b(?:parameter|localparam)\b([^;]*?)(?=;|\)\s*\(|\bparameter\b)",
                         mtext, re.S):
        for name, val in re.findall(r"([A-Za-z_]\w*)\s*=\s*([^,;)]+)", m.group(1)):
            out.setdefault(name, val.strip())
    return out


def instance_params(entry: dict, g, texts: dict[str, str]) -> dict:
    """Parameter overrides along the instance path of a submodule FSM, resolved to integer
    literals (sby proves the module standalone, so without them it runs with module defaults).
    {"set": {P: literal}, "unresolved": {P: expr}}; empty for a top-level FSM."""
    out = {"set": {}, "unresolved": {}}
    if g.module == entry["top"]:
        return out
    mod = entry["top"]
    env = {k: v.replace(" ", "") for k, v in _param_defaults(_mod_text(texts, mod)).items()}
    for inst in g.instance.split(".")[1:]:
        child, over = _instance(texts, mod, inst, params=True)
        if child is None:
            break
        res, bad = {}, {}
        for k, e in over.items():
            v = env.get(e.replace(" ", ""), e.replace(" ", ""))
            (res if _LIT.fullmatch(v) else bad)[k] = v if _LIT.fullmatch(v) else e
        cenv = {k: v.replace(" ", "") for k, v in _param_defaults(_mod_text(texts, child)).items()}
        env, mod = {**cenv, **res}, child
        out = {"set": res, "unresolved": bad}
    return out if mod == g.module else {"set": {}, "unresolved": {"path": g.instance}}


def find_reset(entry: dict, g, texts: dict[str, str]) -> dict | None:
    """Reset port (name in g.module) and polarity. entry["reset"] = {port, active_low} names the
    top's reset; it is followed down the instance path through named port connections."""
    top = entry["top"]
    cur = dict(entry["reset"]) if entry.get("reset") else module_reset(_mod_text(texts, top))
    if cur is not None and "how" not in cur:
        cur["how"] = "entry"
    path = g.instance.split(".")[1:] if g.module != top else []
    mod = top
    for inst in path:
        child, conns = _instance(texts, mod, inst)
        if child is None:
            break
        nxt = None
        for port, expr in conns.items():
            if cur is None:
                break
            e = expr.replace(" ", "")
            if e == cur["port"]:
                nxt = {"port": port, "active_low": cur["active_low"]}
            elif e in (f"!{cur['port']}", f"~{cur['port']}"):
                nxt = {"port": port, "active_low": not cur["active_low"]}
        if nxt:
            nxt["how"] = f"{cur['how']} via {mod}.{inst}"
        mod, cur = child, nxt
    if mod != g.module:
        cur = None
    return cur or module_reset(_mod_text(texts, g.module))


def top_first(entry: dict) -> dict:
    """Copy of `entry` whose file list starts with the file that defines the top module (some
    designs guard their read order with `error, e.g. picosoc.v before picorv32.v)."""
    texts = read_texts(entry)
    loc = find_module(texts, entry["top"])
    if not loc:
        return dict(entry)
    files = sorted(entry["files"], key=lambda f: str(_abs(f)) != loc[0])
    return {**entry, "files": files}


def read_texts(entry: dict) -> dict[str, str]:
    out = {}
    for f in entry["files"]:
        p = _abs(f)
        out[str(p)] = mask_comments(p.read_text(encoding="utf-8", errors="replace"))
    return out


# ------------------------------------------------------------------ monitor injection


def _lit(w: int | None, v: int) -> str:
    return f"{w}'d{v}" if w else str(v)


def monitor(g, clk: str, rst: dict, allowed: list[tuple[int, int]], known: list[int],
            covers: list[tuple[str, int, int]],
            forbid: list[tuple[int, int]] | None = None) -> str:
    """`forbid` given: assert only that none of these (prev, state) pairs ever occurs (used at
    the real top, where the state may also take values outside the graph)."""
    st, w = g.state_reg, g.width
    decl = f"[{w - 1}:0]" if w else f"[$bits({st})-1:0]"
    act = f"!{rst['port']}" if rst["active_low"] else rst["port"]
    edge = " ||\n      ".join(f"(x4_prev == {_lit(w, a)} && {st} == {_lit(w, b)})"
                              for a, b in allowed) or "1'b0"
    kn = " || ".join(f"{st} == {_lit(w, v)}" for v in known) or "1'b1"
    if forbid is not None:
        kn = "1'b1"
        edge = "!(" + (" ||\n      ".join(f"(x4_prev == {_lit(w, a)} && {st} == {_lit(w, b)})"
                                         for a, b in forbid) or "1'b0") + ")"
    cov = "\n".join(f"    if (x4_chk) x4_c{i}: cover(x4_prev == {_lit(w, a)} && {st} == "
                    f"{_lit(w, b)});  // {tid}" for i, (tid, a, b) in enumerate(covers))
    return f"""
`ifdef X4_FORMAL
  // ---- x4 fsm_prove monitor (injected into a copy; not part of the design) ----
  reg {decl} x4_prev;
  reg x4_pv = 1'b0;
  reg x4_prst = 1'b1;
  reg x4_init = 1'b1;
  wire x4_rst = {act};
  always @(posedge {clk}) begin
    x4_prev <= {st};
    x4_pv <= 1'b1;
    x4_prst <= x4_rst;
    x4_init <= 1'b0;
  end
  always @(*) if (x4_init) assume(x4_rst);
  wire x4_chk = x4_pv && !x4_prst && !x4_rst;
  always @(*) begin
    if (x4_chk) x4_known: assert({kn});
    if (x4_chk) x4_edge: assert(x4_prev == {st} ||
      {edge});
  end
  always @(*) begin
{cov}
  end
`endif
"""


def _write_src(entry, g, work: Path, mon: str) -> list[str]:
    src = work / "src"
    src.mkdir(parents=True, exist_ok=True)
    names = []
    for i, f in enumerate(entry["files"]):
        p = _abs(f)
        raw = p.read_text(encoding="utf-8", errors="replace")
        loc = find_module({str(p): mask_comments(raw)}, g.module)
        if loc:
            raw = raw[:loc[2]] + mon + raw[loc[2]:]
        name = f"f{i}_{re.sub(r'[^A-Za-z0-9_.]', '_', p.name)}"
        (src / name).write_text(raw, encoding="utf-8")
        names.append(name)
    return names


def sby_text(entry, g, names: list[str], depth: int, multiclock: bool = False,
             params: dict | None = None, top: str | None = None,
             timeout: float | None = None) -> str:
    """`top` (default g.module) is the sby top; chparam only applies to a standalone module.
    Tasks: prove / cover at `depth`, deep = BMC at depth * DEEP_FACTOR. The directory of every
    original file is on the include path (the copies live in src/, relative `include`s would
    otherwise break)."""
    chp = "" if top else "".join(f"chparam -set {k} {v} {g.module}\n"
                                 for k, v in (params or {}).items())
    dirs = [str(_abs(d)) for d in entry.get("include_dirs") or []]
    dirs += [str(_abs(f).parent) for f in entry["files"]]
    inc = " ".join(f'-I "{d}"' if " " in d else f"-I{d}" for d in dict.fromkeys(dirs))
    opt = ("\nmulticlock on" if multiclock else "") + \
        (f"\ntimeout {max(1, int(timeout))}" if timeout else "")
    dfn = " ".join(f"-D{d}" for d in entry.get("defines") or [])
    files = "\n".join(f"src/{n}" for n in names)
    return f"""[tasks]
prove
cover
deep

[options]
prove: mode prove
prove: depth {depth}
cover: mode cover
cover: depth {depth}
deep: mode bmc
deep: depth {depth * DEEP_FACTOR}{opt}

[engines]
{SOLVER}

[script]
read -sv -DX4_FORMAL {inc} {dfn} {' '.join(names)}
{chp}prep -top {top or g.module}
cover: chformal -assert -remove

[files]
{files}
"""


# ------------------------------------------------------------------ result parsing


def _vcd_last(path: Path, names: set[str]) -> dict[str, str]:
    """Final values of top-scope vars `names` in a VCD."""
    ids, vals, depth = {}, {}, 0
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith("$scope"):
            depth += 1
        elif s.startswith("$upscope"):
            depth -= 1
        elif s.startswith("$var") and depth == 1:
            parts = s.split()
            if len(parts) >= 5 and parts[4] in names:
                ids.setdefault(parts[3], parts[4])
        elif s and s[0] in "bB" and " " in s:
            v, k = s[1:].split()
            if k in ids:
                vals[ids[k]] = v
        elif s and s[0] in "01xz" and s[1:] in ids:
            vals[ids[s[1:]]] = s[0]
    return vals


def _bits(v: str | None) -> int | None:
    return int(v, 2) if v and re.fullmatch(r"[01]+", v) else None


def _sby(work: Path, task: str, timeout: float):
    """Run one sby task; the .sby carries sby's own `timeout` (it stops its solvers cleanly),
    the wall-clock cap is a few seconds longer as a backstop."""
    sby = x4_tools.which("sby") or "sby"
    r = x4_tools.run_capped([sby, "-f", "x4.sby", task], cwd=work, timeout=timeout + 10)
    log = (r.stdout or "") + (r.stderr or "")
    (work / f"{task}.log").write_text(log, encoding="utf-8")
    done = re.search(r"DONE \((\w+), rc=(\d+)\)", log)
    return (done.group(1) if done else ("TIMEOUT" if r.returncode == 124 else "ERROR")), log


def _basecase_passed(log: str) -> bool:
    return bool(re.search(r"returned pass for basecase|basecase: .*[Ss]tatus: passed", log))


def _failed_assert(log: str) -> str | None:
    m = re.search(r"failed assertion (\S+)", log)
    return m.group(1) if m else None


def _tail(s: str, n: int = 20) -> str:
    return "\n".join(s.strip().splitlines()[-n:])


# ------------------------------------------------------------------ main entry


def _setup(entry: dict, g):
    vals = {s.id: s.value for s in g.states}
    if any(v is None for v in vals.values()):
        return None, {"status": "skipped(no-values)"}
    texts = read_texts(entry)
    if not find_module(texts, g.module):
        return None, {"status": "skipped(frontend)", "reason": f"module {g.module} not found"}
    rst = find_reset(entry, g, texts)
    if rst is None:
        return None, {"status": "skipped(no-reset)", "reason": "no reset port found"}
    clk = find_clock(_mod_text(texts, g.module), rst["port"])
    if clk is None:
        return None, {"status": "skipped(no-clock)", "reason": "no clock found"}
    return {"vals": vals, "rst": rst, "clk": clk,
            "params": instance_params(entry, g, texts)}, None


def _run_prove(entry, g, ctx, allowed, known, covers, work, depth, budget, task="prove"):
    work.mkdir(parents=True, exist_ok=True)
    names = _write_src(entry, g, work, monitor(g, ctx["clk"], ctx["rst"], sorted(allowed),
                                               sorted(known), covers))
    (work / "x4.sby").write_text(sby_text(entry, g, names, depth, ctx.get("multiclock", False),
                                          ctx["params"]["set"], timeout=budget),
                                 encoding="utf-8")
    res, log = _sby(work, task, budget)
    if res == "ERROR" and "opposite polarity" in log and not ctx.get("multiclock"):
        ctx["multiclock"] = True  # both clock edges used (spimemio): clk2fflogic via sby
        return _run_prove(entry, g, ctx, allowed, known, covers, work, depth, budget, task)
    return res, log


def _cex(work: Path, g, induct: bool = False, task: str = "prove"):
    """(x4_prev, state) at the last step of the basecase (or induction) counterexample."""
    vcds = sorted((work / f"x4_{task}").glob(f"engine_*/trace{'_induct' if induct else ''}.vcd"))
    if not vcds:
        return None, None
    v = _vcd_last(vcds[0], {"x4_prev", g.state_reg})
    return _bits(v.get("x4_prev")), _bits(v.get(g.state_reg))


def _cover(work: Path, covers, budget) -> dict:
    status, log = _sby(work, "cover", budget)
    reached = {}
    for m in re.finditer(r"Reached cover statement in step (\d+) at [^\n]*?x4_c(\d+)\b", log):
        reached.setdefault(int(m.group(2)), int(m.group(1)))
    for m in re.finditer(r"Reached cover statement at [^\n]*?x4_c(\d+)\b[^\n]*? in step (\d+)",
                         log):  # older yosys-smtbmc wording
        reached.setdefault(int(m.group(1)), int(m.group(2)))
    uncovered = [covers[i][0] for i in range(len(covers)) if i not in reached]
    return {"cover_status": status, "covered": len(reached), "total": len(covers),
            "uncovered": uncovered,
            "uncovered_reason": "not reached within depth from reset (deeper or unreachable)"
            if uncovered else None,
            "cover_steps": {covers[i][0]: s for i, s in sorted(reached.items())},
            "cover_log_tail": _tail(log, 8)}


def _cover_run(entry, g, ctx, mon: str, covers, work: Path, depth: int, budget: float,
               top: str | None = None, task: str = "cover"):
    """Write a fresh copy with monitor `mon` and run one sby task (cover -> _cover result,
    prove -> (status, log)). `top` set: sby top is the real top (no chparam)."""
    work.mkdir(parents=True, exist_ok=True)
    names = _write_src(entry, g, work, mon)
    (work / "x4.sby").write_text(sby_text(entry, g, names, depth, ctx.get("multiclock", False),
                                          None if top else ctx["params"]["set"], top=top,
                                          timeout=budget), encoding="utf-8")
    return _cover(work, covers, budget) if task == "cover" else _sby(work, task, budget)


def _top_cover(entry, g, ctx, missing: list[dict], work: Path, depth: int, deadline: float):
    """Submodule FSM: try to reach each missing edge from the real top (monitor still inside
    g.module, sby top = entry top, cover mode). Reached -> kind "edge" (reproduced at the
    elaborated top). Not reached -> a top-level proof that the edge never occurs (`top_proof`):
    PASS -> stays "unconstrained" (only reachable with inputs the parent never drives);
    basecase FAIL -> "edge"; otherwise unknown (unconstrained, or deeper than depth)."""
    covers = [(f"m.{i}", m["src_value"], m["dst_value"]) for i, m in enumerate(missing)]
    res = _cover_run(entry, g, ctx, monitor(g, ctx["clk"], ctx["rst"], [], [], covers), covers,
                     work, depth, deadline - time.time(), top=entry["top"])
    rest = []
    for i, m in enumerate(missing):
        step = res["cover_steps"].get(f"m.{i}")
        if step is not None:
            m["kind"], m["top_cover"] = "edge", f"reached from {entry['top']} in step {step}"
        else:
            m["top_cover"] = (f"not reached from {entry['top']} within depth {depth}"
                              if res["cover_status"] in ("PASS", "FAIL")
                              else f"top-level cover {res['cover_status']}")
            rest.append(m)
    left = deadline - time.time()
    if not rest or left <= 5:
        for m in rest:
            m["top_proof"] = "not run (time)"
        return
    forbid = [(m["src_value"], m["dst_value"]) for m in rest]
    mon = monitor(g, ctx["clk"], ctx["rst"], [], [], [], forbid=forbid)
    status, log = _cover_run(entry, g, ctx, mon, [], work / "proof", depth, left,
                             top=entry["top"], task="prove")
    for m in rest:
        if status == "PASS":
            m["top_proof"] = f"proven: never occurs under {entry['top']}"
        elif status == "FAIL":
            m["kind"], m["top_proof"] = "edge", f"basecase reaches an edge from {entry['top']}"
        else:
            m["top_proof"] = f"unknown ({status.lower()}; unconstrained or deeper than {depth})"


def _attempt(entry, g, ctx, st, wdir: Path, depth: int, left: float, task: str = "prove"):
    """One sby prove run; on a frontend error retry once with the top module's file first."""
    res, log = _run_prove(entry, g, ctx, st["allowed"], st["known"], st["covers"], wdir, depth,
                          left, task)
    if res == "ERROR" and "ERROR" in log:
        tf = top_first(entry)
        if tf["files"] != entry["files"]:
            shutil.rmtree(wdir)
            entry = tf
            res, log = _run_prove(entry, g, ctx, st["allowed"], st["known"], st["covers"], wdir,
                                  depth, left, task)
    return entry, res, log


def _iterate(entry, g, ctx, st, work: Path, depth: int, deadline: float,
             task: str = "prove") -> dict:
    """Prove (task "prove") or BMC at depth * DEEP_FACTOR (task "deep"); on each
    counterexample record the observed edge, allow it and run again."""
    name = {s.value: s.name for s in g.states}
    status, log, k, induct = "error", "", 0, None
    for k in range(MAX_ITER):
        left = deadline - time.time()
        if left <= 5:
            status = "timeout"
            break
        entry, res, log = _attempt(entry, g, ctx, st, work / f"iter{k}", depth, left, task)
        if res == "PASS":
            status = "proven" if task == "prove" else f"bounded({depth * DEEP_FACTOR})"
            break
        if res == "UNKNOWN" and _basecase_passed(log):
            status = f"bounded({depth})"
            a, b = _cex(work / f"iter{k}", g, induct=True)
            if a is not None and b is not None and a != b:
                induct = {"src": name.get(a, f"code:{a}"), "dst": name.get(b, f"code:{b}")}
            break
        if res != "FAIL":
            status = "skipped(frontend)" if "ERROR" in log else res.lower()
            break
        a, b = _cex(work / f"iter{k}", g, task=task)
        if a is None or b is None or (a, b) in st["allowed"] or a == b:
            status = "failed(unparsed-cex)"
            break
        unc = st["sub"] and (a, b) not in st["semantic"]
        st["missing"].append({"src": name.get(a, f"code:{a}"), "dst": name.get(b, f"code:{b}"),
                              "src_value": a, "dst_value": b, "iteration": k,
                              "phase": "prove" if task == "prove"
                              else f"bmc({depth * DEEP_FACTOR})",
                              "kind": "unconstrained" if unc else "edge"})
        st["allowed"].add((a, b))
        st["known"].add(b)
    err = (re.search(r"ERROR: .*", log) if not status.startswith(("proven", "bounded"))
           else None)
    return {"status": status, "log": log, "k": k, "induct": induct, "entry": entry,
            "error": err.group(0)[:300] if err else None}


def _unreachable(entry, g, ctx, st, uncovered: list[str], work: Path, depth: int,
                 deadline: float) -> dict:
    """Uncovered transitions: prove them absent (allowed set without them). PASS -> every
    remaining one is proven unreachable after reset; a counterexample shows one is reachable
    (deeper than the cover found, or only via a long prefix); otherwise unknown."""
    pair = {tid: (a, b) for tid, a, b in st["covers"]}
    drop = {pair[t] for t in uncovered}
    st2 = {"allowed": set(st["allowed"]) - drop, "known": set(st["known"]), "missing": [],
           "sub": False, "covers": [], "semantic": set()}
    r = _iterate(entry, g, ctx, st2, work, depth, deadline)
    found = {(m["src_value"], m["dst_value"]) for m in st2["missing"]}
    reach = [t for t in uncovered if pair[t] in found]
    rest = [t for t in uncovered if pair[t] not in found]
    ok = r["status"] == "proven"
    return {"status": r["status"], "proven_unreachable": rest if ok else [],
            "reachable": reach, "unknown": [] if ok else rest}


def _deep(entry, g, ctx, st, work: Path, depth: int, deadline: float) -> tuple[dict, dict]:
    """bounded(depth): one BMC pass at depth * DEEP_FACTOR (counter-gated edges such as
    traffic_light's 60-tick countdown lie deeper than the default depth)."""
    t, n0 = time.time(), len(st["missing"])
    r = _iterate(entry, g, ctx, st, work, depth, deadline, task="deep")
    return r, {"depth": depth * DEEP_FACTOR, "status": r["status"],
               "found": len(st["missing"]) - n0, "seconds": round(time.time() - t, 2)}


def _deep_cover(entry, g, ctx, st, out: dict, work: Path, depth: int, budget: float) -> None:
    """Uncovered transitions: one more cover pass at depth * DEEP_FACTOR (only those)."""
    sub = [c for c in st["covers"] if c[0] in set(out["uncovered"])]
    mon = monitor(g, ctx["clk"], ctx["rst"], sorted(st["allowed"]), sorted(st["known"]), sub)
    res = _cover_run(entry, g, ctx, mon, sub, work, depth * DEEP_FACTOR, budget)
    out["cover_deep"] = {"depth": depth * DEEP_FACTOR, "status": res["cover_status"],
                         "covered": res["covered"], "of": len(sub)}
    for tid, step in res["cover_steps"].items():
        out["cover_steps"][tid] = step
        out["cover_depth"][tid] = depth * DEEP_FACTOR
    out["covered"] += res["covered"]
    out["uncovered"] = [t for t in out["uncovered"] if t not in res["cover_steps"]]


def _covers(r, g, ctx, st, out: dict, work: Path, depth: int, t0: float, timeout: float):
    """Cover every non-self transition at `depth`, then the uncovered ones deeper. Keeps
    covered + len(uncovered) == total even when a pass cannot run (`cover_status`)."""
    left = timeout - (time.time() - t0)
    ids = [c[0] for c in st["covers"]]
    out.update({"total": len(ids), "covered": 0, "uncovered": ids, "cover_steps": {},
                "cover_depth": {}})
    if not ids:
        out["cover_status"] = "n/a (no non-self transitions)"
        return
    if r["status"] in ("skipped(frontend)", "error") or left <= 5:
        out["cover_status"] = "skipped(time)" if left <= 5 else f"skipped({r['status']})"
        return
    out.update(_cover(work / f"iter{r['k']}", st["covers"], left))
    out["cover_depth"] = {t: depth for t in out["cover_steps"]}
    left = timeout - (time.time() - t0)
    if out["uncovered"] and left > 10:
        _deep_cover(r["entry"], g, ctx, st, out, work / "cover_deep", depth, left * DEEP_SHARE)
    if out["uncovered"]:
        out["uncovered_reason"] = "not reached from reset within the cover depth (deeper or " \
                                  "unreachable)"


def prove(entry: dict, g, work: Path, *, depth: int = 20, timeout: float = 300) -> dict:
    """G6 for one FSM. {status, depth, solver, covered, total, uncovered[], missing_edges[],
    seconds, log_tail, reset, clock, params, iterations, induction_cex, deep, cover_status,
    cover_steps, cover_depth, uncovered_check}; covered + len(uncovered) == total always."""
    t0 = time.time()
    work = Path(work)
    base = {"depth": depth, "solver": SOLVER, "covered": 0, "total": 0, "uncovered": [],
            "missing_edges": [], "params": {}, "log_tail": ""}
    if x4_tools.which("sby") is None:
        return {**base, "status": "skipped(no-sby)", "seconds": 0.0}
    ctx, skip = _setup(entry, g)
    if skip:
        n = sum(t.src != t.dst for t in g.transitions)
        return {**base, **skip, "total": n, "uncovered": [t.id for t in g.transitions
                                                         if t.src != t.dst],
                "cover_status": "skipped", "seconds": round(time.time() - t0, 2)}
    vals = ctx["vals"]
    nonself = [t for t in g.transitions if t.src != t.dst]
    st = {"allowed": {(vals[t.src], vals[t.dst]) for t in nonself},
          "known": set(vals.values()), "missing": [], "sub": g.module != entry["top"],
          "covers": [(t.id, vals[t.src], vals[t.dst]) for t in nonself],
          "semantic": {(vals[t.src], vals[t.dst]) for t in nonself if "semantic" in t.seen_by}}
    if work.exists():
        shutil.rmtree(work)
    r = _iterate(entry, g, ctx, st, work, depth, t0 + timeout)
    status, final, deep = r["status"], r["status"], None
    left = timeout - (time.time() - t0)
    if status == f"bounded({depth})" and left > 10:
        r2, deep = _deep(r["entry"], g, ctx, st, work / "deep", depth,
                         time.time() + left * DEEP_SHARE)
        if r2["status"].startswith("bounded"):
            status = final = r2["status"]
        elif deep["found"]:
            final = r2["status"]
    missing = st["missing"]
    left = timeout - (time.time() - t0)
    if any(m["kind"] == "unconstrained" for m in missing) and left > 5:
        _top_cover(r["entry"], g, ctx, missing, work / "topcover", depth, t0 + timeout)
    if missing:
        status = ("failed(edge)" if any(m["kind"] == "edge" for m in missing)
                  else "failed(unconstrained)")
    out = {**base, "status": status, "missing_edges": missing, "iterations": r["k"] + 1,
           "with_missing_added": final if missing else None, "deep": deep,
           # bounded: last step of the induction counterexample, a candidate edge that is not
           # reachable within `depth` from reset (or not at all); never added to the graph
           "induction_cex": r["induct"], "failed_assertion": _failed_assert(r["log"]),
           "reset": ctx["rst"], "clock": ctx["clk"], "submodule": st["sub"],
           "multiclock": bool(ctx.get("multiclock")), "error": r["error"],
           "params": ctx["params"],
           "file_order": r["entry"]["files"], "log_tail": _tail(r["log"])}
    _covers(r, g, ctx, st, out, work, depth, t0, timeout)
    left = timeout - (time.time() - t0)
    if out["uncovered"] and left > 5 and r["status"] in ("proven", f"bounded({depth})"):
        out["uncovered_check"] = _unreachable(r["entry"], g, ctx, st, out["uncovered"],
                                              work / "unreach", depth, time.time() + left)
    out["seconds"] = round(time.time() - t0, 2)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("entry")
    ap.add_argument("graph")
    ap.add_argument("work")
    ap.add_argument("--depth", type=int, default=20)
    ap.add_argument("--timeout", type=float, default=300)
    a = ap.parse_args(argv)
    entry = json.loads(Path(a.entry).read_text())
    g = fsm_spec.FsmGraph.model_validate_json(Path(a.graph).read_text())
    res = prove(entry, g, Path(a.work), depth=a.depth, timeout=a.timeout)
    print(json.dumps({k: v for k, v in res.items() if "log_tail" not in k}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
