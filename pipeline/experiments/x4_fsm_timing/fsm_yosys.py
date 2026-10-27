"""x4 G1: cross-check an FsmGraph against Yosys `fsm_detect/fsm_extract/fsm_info` (forced).

    uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/fsm_yosys.py \
        ENTRY.json FSMGRAPH.json WORKDIR

Script per attempt (serial, run_capped, timeout 120 s):
    read_verilog -sv FILES; hierarchy -top TOP; <pre>;
    setattr -set fsm_encoding "auto" <module>/w:<reg>; fsm_detect; fsm_extract; fsm_info
When that table has only_yosys edges and Yosys-internal control inputs, the run is repeated with
`fsm_opt; opt_clean; fsm_opt; fsm_expand; opt_clean; fsm_opt; fsm_info` (fsm_expand folds
state-derived gates such as `pos == D && b` into the FSM; timeout 30 s, `expand`, the first
comparison kept as `plain`).
`fsm_detect` declines most hand-written FSMs ("don't seem to benefit from recoding") unless the
attribute is set first, so G1 always runs forced (`forced: true`). `<pre>` is tried in order
`proc; opt` (the plan's script), `proc; opt -nosdff -nodffe`, `proc; opt_clean`: plain `opt`
folds the state register into an enable flip-flop and fsm_extract then fails with "incomplete
input selection tree root" (seen on uart_tx), so the first script that yields the FSM is used
and recorded in `script`. A synchronous reset (or a reset term in the next-state logic) is an
fsm input and shows up as X -> reset_state rows (sequence_detector, fsm_ps2data, fsm_hdlc,
reservoir); rows whose reset-input bit (fsm_prove.find_reset) is active are dropped and counted
in `reset_rows_dropped` (tying the port with `connect -set` was tried and rejected: it turns an
async-reset $adff into $dff and the reset state disappears from the table).
When read_verilog fails the read is retried with the top module's file first, then with
`plugin -i slang; read_slang`. Yosys state codes are mapped to L1 names through the state values
of the FsmGraph; (src, dst) pair sets are compared without input conditions and without
self-loops (Yosys lists every hold; syntactic extraction lists only written ones), self-loop
differences are reported separately. Yosys tables are structural: they can list edges that are
unreachable from reset, so `disagree` is a lead for G6, not a verdict. Rows that fix an
`$fsm$oldstate\\<reg> [k]` input against the source code's bit k are infeasible and dropped
(`infeasible_rows_dropped`); remaining Yosys-internal control inputs are listed in
`inputs_internal` (rows over them may still be infeasible combinations).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
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

PRE = ["proc; opt", "proc; opt -nosdff -nodffe", "proc; opt_clean"]
# Refinement: fsm_expand (as in Yosys' own `fsm` flow) merges auxiliary gates between the state
# register and the next-state logic into the FSM; without it a state test such as
# `pos == D && b` stays a free control input and fsm_info lists infeasible rows
# (S1_sequence_detector). It can blow up (picorv32 cpu_state: 8.7M rows), so it only runs when
# the plain table disagrees through Yosys-internal inputs, with its own short timeout.
EXPAND = "fsm_opt; opt_clean; fsm_opt; fsm_expand; opt_clean; fsm_opt; fsm_info"
TIMEOUT = 120.0
EXPAND_TIMEOUT = 30.0


def _abs(p: str) -> str:
    q = Path(p)
    return str(q if q.is_absolute() else x4_tools.ROOT / q)


def _q(p: str) -> str:
    return f'"{p}"' if " " in p else p


def _reads(entry: dict, slang: bool) -> str:
    files = " ".join(_q(_abs(f)) for f in entry["files"])
    inc = " ".join(f"-I{_q(_abs(d))}" for d in entry.get("include_dirs") or [])
    dfn = " ".join(f"-D{d}" for d in entry.get("defines") or [])
    if slang:
        return f"plugin -i slang; read_slang {files} --top {entry['top']}"
    return f"read_verilog -sv {inc} {dfn} {files}"


def script(entry: dict, g, pre: str, slang: bool = False, post: str = "fsm_info") -> str:
    sel = f"{g.module}/w:{g.state_reg} $paramod*{g.module}*/w:{g.state_reg}"
    return (f"{_reads(entry, slang)}; hierarchy -top {entry['top']}; {pre}; "
            f'setattr -set fsm_encoding "auto" {sel}; fsm_detect; fsm_extract; {post}')


# ------------------------------------------------------------------ fsm_info parsing
_FSM_HDR = re.compile(r"^FSM `(.+?)' from module `(.+?)':", re.M)
_INFO = re.compile(r"Information on FSM \S+ \((.+?)\):")
_ENC = re.compile(r"^\s+(\d+):\s+(\d+)'([01xz\-]+)", re.M)
_TR = re.compile(r"^\s+\d+:\s+(\d+)\s+\d*'?([01\-xz]*)\s+->\s+(\d+)\s+\S+", re.M)
_IN = re.compile(r"^\s+(\d+):\s+(.+?)\s*$", re.M)


def parse_fsm_info(log: str) -> list[dict]:
    """Every FSM block printed by fsm_info: {cell, module, reg, codes{idx: bits},
    reset_idx, transitions[(i, j)]}."""
    out = []
    heads = list(_FSM_HDR.finditer(log))
    for k, m in enumerate(heads):
        end = heads[k + 1].start() if k + 1 < len(heads) else len(log)
        blk = log[m.end():end]
        reg = _INFO.search(blk)
        enc_part = blk.split("State encoding:", 1)[-1].split("Transition Table", 1)[0]
        codes, reset_idx = {}, None
        for e in _ENC.finditer(enc_part):
            codes[int(e.group(1))] = e.group(3)
            line = enc_part[e.start():enc_part.find("\n", e.end())]
            if "RESET STATE" in line:
                reset_idx = int(e.group(1))
        tr_part = blk.split("Transition Table", 1)[-1] if "Transition Table" in blk else ""
        trs = [(int(t.group(1)), int(t.group(3)), t.group(2)) for t in _TR.finditer(tr_part)]
        in_part = blk.split("Input signals:", 1)[-1].split("Output signals:", 1)[0]
        inputs = {int(i.group(1)): i.group(2).lstrip("\\") for i in _IN.finditer(in_part)}
        out.append({"cell": m.group(1), "module": m.group(2),
                    "reg": reg.group(1).lstrip("\\") if reg else None, "inputs": inputs,
                    "codes": codes, "reset_idx": reset_idx, "transitions": trs})
    return out


def _module_match(yname: str, module: str) -> bool:
    """Plain name, hashed `$paramod$<hash>\\<module>` or short
    `$paramod\\<module>\\P=<val>...` (parameter overrides)."""
    y = yname.lstrip("\\")
    pat = r"\$paramod(\$[0-9a-f]+)?\\" + re.escape(module) + r"(\\.*)?"
    return y == module or re.fullmatch(pat, y, re.S) is not None


def _pick(fsms: list[dict], g) -> dict | None:
    for f in fsms:
        if _module_match(f["module"], g.module) and f["reg"] == g.state_reg:
            return f
    return None


def _decline_reason(log: str) -> str:
    for pat in (r"fsm extraction failed: .*", r"Not marking .*", r"Doesn't look like.*",
                r"don't seem to benefit.*", r"ERROR: .*"):
        m = re.search(pat, log)
        if m:
            return m.group(0).strip()
    return "no FSM cell for the state register in fsm_info"


# ------------------------------------------------------------------ comparison


def _reset_rows(yf: dict, rst: dict | None) -> set[int]:
    """Rows taken only while the reset input is active (synchronous reset or a reset term in
    the next-state logic): that is the reset transition, drawn as the entry arrow."""
    if not rst:
        return set()
    idx = [i for i, n in yf["inputs"].items() if n == rst["port"]]
    if not idx:
        return set()
    act = "0" if rst["active_low"] else "1"
    out = set()
    for k, (_, _, pat) in enumerate(yf["transitions"]):
        pos = len(pat) - 1 - idx[0]  # pattern is MSB first, input 0 is the last character
        if 0 <= pos < len(pat) and pat[pos] == act:
            out.add(k)
    return out


_OLD = re.compile(r"\$fsm\$oldstate\\(.+?)(?: \[(\d+)\])?")


def _infeasible_rows(yf: dict, reg: str) -> set[int]:
    """Rows that fix an input `$fsm$oldstate\\<reg> [k]` (the current state's own bit k, left
    as a control input when plain `opt` is skipped) to a value that contradicts bit k of the
    row's source code: they can never fire."""
    bits_in = {}
    for i, n in yf["inputs"].items():
        m = _OLD.fullmatch(n)
        if m and m.group(1).lstrip("\\") == reg:
            bits_in[i] = int(m.group(2) or 0)
    out = set()
    for k, (a, _, pat) in enumerate(yf["transitions"]):
        code = yf["codes"].get(a) or ""
        for i, b in bits_in.items():
            pos, cpos = len(pat) - 1 - i, len(code) - 1 - b
            if 0 <= pos < len(pat) and 0 <= cpos < len(code) and pat[pos] in "01" \
                    and code[cpos] in "01" and pat[pos] != code[cpos]:
                out.add(k)
    return out


def internal_inputs(yf: dict) -> list[str]:
    """Control inputs that are Yosys-internal cells (`$...$eq$7_Y`, `$fsm$oldstate...`), not
    design signals; when any remain, rows over them may be infeasible combinations."""
    return sorted(n for n in yf["inputs"].values() if n.startswith("$"))


def compare(g, yf: dict, rst: dict | None = None) -> dict:
    by_val = {s.value: s.name for s in g.states if s.value is not None}

    def name(idx: int) -> str:
        bits = yf["codes"].get(idx)
        if bits is None or not re.fullmatch(r"[01]+", bits):
            return f"code:{bits}"
        return by_val.get(int(bits, 2), f"code:{int(bits, 2)}")

    ids = {s.id: s.name for s in g.states}
    l1 = {(ids.get(t.src, t.src), ids.get(t.dst, t.dst)) for t in g.transitions}
    drop = _reset_rows(yf, rst)
    infeasible = _infeasible_rows(yf, g.state_reg) - drop
    drop |= infeasible
    ys = {(name(a), name(b)) for k, (a, b, _) in enumerate(yf["transitions"]) if k not in drop}
    l1_n, ys_n = {p for p in l1 if p[0] != p[1]}, {p for p in ys if p[0] != p[1]}
    l1_s, ys_s = l1 - l1_n, ys - ys_n
    reset_y = name(yf["reset_idx"]) if yf["reset_idx"] is not None else None
    reset_l1 = next((s.name for s in g.states if s.reset), None)
    return {
        "status": "agree" if l1_n == ys_n else "disagree",
        "only_l1": sorted(map(list, l1_n - ys_n)), "only_yosys": sorted(map(list, ys_n - l1_n)),
        "self_loops_only_l1": sorted(a for a, _ in l1_s - ys_s),
        "self_loops_only_yosys": sorted(a for a, _ in ys_s - l1_s),
        "states_yosys": sorted({name(i) for i in yf["codes"]}),
        "reset_yosys": reset_y, "reset_agrees": reset_y is None or reset_y == reset_l1,
        "codes": {str(i): b for i, b in sorted(yf["codes"].items())},
        "reset_rows_dropped": len(drop) - len(infeasible),
        "infeasible_rows_dropped": len(infeasible),
        "inputs_internal": internal_inputs(yf),
    }


def _tail(s: str, n: int = 25) -> str:
    return "\n".join(s.strip().splitlines()[-n:])


def _run(entry: dict, g, pre: str, slang: bool, work: Path, post: str = "fsm_info",
         tag: str = "g1", timeout: float = TIMEOUT):
    ys = work / f"{tag}.ys"
    txt = script(entry, g, pre, slang, post).replace(";", "\n")
    ys.write_text("\n".join(x.strip() for x in txt.splitlines() if x.strip()) + "\n",
                  encoding="utf-8")
    r = x4_tools.run_capped([x4_tools.which("yosys") or "yosys", "-s", str(ys)], cwd=work,
                            timeout=timeout)
    log = (r.stdout or "") + (r.stderr or "")
    keep = log if r.returncode == 0 else _tail(log, 200)  # a timed-out expand can be ~100 MB
    (work / f"{tag}.log").write_text(keep, encoding="utf-8")
    return r.returncode, log


def _refine(ent, g, pre: str, slang: bool, work: Path, rst, res: dict) -> dict:
    """Re-run with the fsm_expand flow; its comparison replaces `res` when it parses, and
    the plain one is kept under `plain`."""
    rc, log = _run(ent, g, pre, slang, work, EXPAND, "g1_expand", EXPAND_TIMEOUT)
    yf = _pick(parse_fsm_info(log), g) if rc == 0 else None
    if not (yf and yf["transitions"]):
        why = "timeout" if rc == 124 else f"rc={rc}" if rc else "no FSM after fsm_expand"
        return {**res, "expand": f"not used ({why})"}
    new = compare(g, yf, rst)
    plain = {k: res[k] for k in ("status", "only_l1", "only_yosys", "inputs_internal")}
    return {**new, "expand": "used", "plain": plain,
            "script": script(ent, g, pre, slang, EXPAND)}


def check(entry: dict, g, work: Path) -> dict:
    """G1 for one FSM. {status: agree|disagree|yosys_declined|yosys_unparsed|skipped, forced,
    only_l1, only_yosys, script, log_tail, ...}."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    base = {"forced": True, "only_l1": [], "only_yosys": [], "yosys": x4_tools.which("yosys")}
    if base["yosys"] is None:
        return {**base, "status": "skipped", "reason": "yosys not found", "log_tail": ""}
    if any(s.value is None for s in g.states):
        return {**base, "status": "skipped", "reason": "no-values (state codes cannot be mapped)",
                "log_tail": ""}
    rst = base["reset"] = _reset(entry, g)
    fe, ent, slang, rc, log = _frontend(entry, g, work)
    if rc != 0 and (_frontend_failed(log) or rc == 124):
        return {**base, "status": "yosys_unparsed", "frontend": fe, "rc": rc,
                "script": script(ent, g, PRE[0], slang), "log_tail": _tail(log)}
    last, tried = log, []
    for k, pre in enumerate(PRE):
        if k:
            rc, log = _run(ent, g, pre, slang, work)
            last = log
        tried.append(pre)
        if rc != 0:
            continue
        yf = _pick(parse_fsm_info(log), g)
        if yf and yf["transitions"]:
            res = {**compare(g, yf, rst), "script": script(ent, g, pre, slang)}
            if res["only_yosys"] and res["inputs_internal"]:
                res = _refine(ent, g, pre, slang, work, rst, res)
            return {**base, **res, "frontend": fe, "tried": tried, "log_tail": _tail(log, 12)}
    return {**base, "status": "yosys_declined", "reason": _decline_reason(last),
            "frontend": fe, "tried": tried, "log_tail": _tail(last)}


def _frontend(entry: dict, g, work: Path):
    """First reader that parses the design: read_verilog -sv in manifest order, then with the
    top module's file first (picosoc.v must precede picorv32.v), then read_slang."""
    tf = x4_tools.x4("fsm_prove").top_first(entry)
    opts = [("read_verilog -sv", entry, False)]
    if tf["files"] != entry["files"]:
        opts.append(("read_verilog -sv (top file first)", tf, False))
    opts.append(("read_slang", entry, True))
    for opt in opts:
        rc, log = _run(opt[1], g, PRE[0], opt[2], work)
        if not (rc != 0 and _frontend_failed(log)):
            break
    return (*opt, rc, log)


def _reset(entry: dict, g) -> dict | None:
    try:
        fp = x4_tools.x4("fsm_prove")
        return fp.find_reset(entry, g, fp.read_texts(entry))
    except (OSError, ValueError):
        return None


def _frontend_failed(log: str) -> bool:
    head = log.split("Executing HIERARCHY", 1)[0]
    return "ERROR" in head or "syntax error" in head


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    entry = json.loads(Path(argv[0]).read_text())
    g = fsm_spec.FsmGraph.model_validate_json(Path(argv[1]).read_text())
    res = check(entry, g, Path(argv[2]))
    print(json.dumps({k: v for k, v in res.items() if k != "log_tail"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
