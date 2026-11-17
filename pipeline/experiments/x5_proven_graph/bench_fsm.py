"""Open-source FSM extractors scored against proven state graphs.

    python bench_fsm.py OUT WORK [--tools yosys,yosys_new,pyverilog,teroshdl,verilator]

For every audited certificate in OUT whose observation is one state register, each tool is run on
the same RTL the way its users run it, and its drawing is compared with the certificate:

  * extra edge: drawn by the tool, and proven impossible (the certificate is complete);
  * missed edge: happens in an execution from reset (the certificate has a replayed trace), and the
    tool does not draw it;
  * unreachable state: drawn by the tool, and proven never to occur after reset.

Edges are compared without self-loops, which tools draw by different conventions (some never draw
them); self-loops are counted on their own. An edge into the reset state that the tool draws only
because reset can be pulled again is not counted against it: the certificates assume reset is not
reasserted. States are matched by value: a tool that names states, names them by constants of the
RTL, which are read from the source here; a state whose name cannot be resolved is reported.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
YOSYS = {"yosys": "yosys", "yosys_new": str(HOME / "rtl2d-demo/tools/oss-cad-suite/bin/yosys")}
PYV = str(HOME / "rtl2d-demo/benchenv/bin/python")
NODE = str(HOME / "rtl2d-demo/repo/runs/.tools/x3/node/bin/node")
TEROS = HOME / "rtl2d-demo/tools/teroshdl"
VERILATOR = HOME / "rtl2d-demo/tools/oss-cad-suite/bin/verilator"
SV2V = HOME / "rtl2d-demo/tools/sv2v/sv2v-Linux/sv2v"
ENV = dict(os.environ, PATH=str(HOME / "rtl2d-demo/x5w/bin") + ":" + os.environ.get("PATH", ""))


def sh(cmd, cwd, timeout=600):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=ENV)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def order(spec, cert):
    """The source files the proof used (a file Yosys could not read was dropped), in its order."""
    drop = set(cert["engine"].get("files_dropped") or [])
    files = [str(f) for f in spec["files"] if str(f) not in drop]
    if cert["assumptions"].get("source_order") == "top module's file first":
        top = [f for f in files if re.search(r"^\s*module\s+" + re.escape(spec["top"]) + r"\b", Path(f).read_text(errors="replace"), re.M)]
        files = top[:1] + [f for f in files if f not in top[:1]]
    return files


def same_fsm(var, sig):
    """A two-process state machine has a state register and a next-state variable; a tool that shows
    the machine under the next-state name shows the same machine."""
    stem = lambda n: re.sub(r"(_reg|_q|_r|_ff|_cur|_current|_next|_nxt|_d|_n)$", "", n)  # noqa: E731
    return var == sig or (stem(var) == stem(sig) and stem(var) != var and stem(sig) != sig) or (stem(var) == sig) or (stem(sig) == var)


def module_file(spec, mod):
    return next((f for f in spec["files"] if re.search(r"^\s*module\s+" + re.escape(mod) + r"\b", Path(f).read_text(errors="replace"), re.M)), None)


# ---- reading constants of the RTL, to give named states their values ------------------------------
def _lit(v):
    v = v.strip().replace("_", "")
    m = re.fullmatch(r"(\d*)\s*'\s*[sS]?([bBoOdDhH])\s*([0-9a-fA-F]+)", v)
    if m:
        return int(m.group(3), {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(2).lower()])
    return int(v) if re.fullmatch(r"\d+", v) else None


def constants(text):
    """name -> value for localparams, parameters and `define macros with plain literal values."""
    out = {}
    for decl in re.findall(r"\b(?:localparam|parameter)\b([^;]*);", text):
        decl = re.sub(r"^\s*(?:\[[^\]]*\]\s*|integer\s+|logic\s+|reg\s+|bit\s+)*", "", decl)
        for name, val in re.findall(r"([A-Za-z_]\w*)\s*=\s*([^,]+)", decl):
            x = _lit(val)
            if x is not None:
                out[name] = x
    for name, val in re.findall(r"^\s*`define\s+(\w+)\s+([^\s/]+)", text, re.M):
        x = _lit(val)
        if x is not None:
            out["`" + name] = out[name] = x
    return out


def value_of(label, consts):
    label = label.strip()
    if label in consts:
        return consts[label]
    if label.startswith("`") and label[1:] in consts:
        return consts[label[1:]]
    return _lit(label)


# ---- the tools -----------------------------------------------------------------------------------
def yosys_fsm(spec, cert, work, which):
    """Yosys's FSM passes (fsm_detect, fsm_extract, fsm_opt) as its manual runs them, KISS2 out."""
    exe = YOSYS[which]
    if which != "yosys" and not Path(exe).exists():
        return {"status": "not installed"}
    work.mkdir(parents=True, exist_ok=True)
    for f in work.glob("*.kiss2"):
        f.unlink()
    incs = " ".join("-I" + d for d in sorted({str(Path(f).parent) for f in spec["files"]} | set(spec.get("include_dirs") or [])))
    ys = (f"read_verilog -sv -DSYNTHESIS -DYOSYS {incs} {' '.join(order(spec, cert))}\nhierarchy -check -top {spec['top']}\n"
          "proc\nflatten\nopt -nosdff -nodffe\nfsm_detect\nfsm_extract\nfsm_opt\nopt_clean\ntee -q -o info.txt fsm_info\nfsm_export -origenc\n")
    (work / "fsm.ys").write_text(ys)
    # no -q: Yosys 0.71 crashes in quiet mode on picorv32 (exit 139) and runs to the end without it
    rc, log = sh([exe, "-s", "fsm.ys"], work)
    (work / "yosys.log").write_text(log)
    crash = None if rc == 0 else f"exit {rc}" + (" (crashed)" if rc < 0 or rc > 128 else "") + ": " + (log.strip().splitlines() or ["no output"])[-1][:140]
    want = ".".join(cert["scope"]["instance"] + [cert["observation"][0]["signal"]])
    for k in work.glob("*.kiss2"):
        sig = re.search(r"\$fsm\$\\?(.+?)\$\d+\.kiss2$", k.name)
        if not sig or sig.group(1) != want:
            continue
        edges, states, reset = set(), set(), None
        for ln in k.read_text().splitlines():
            if ln.startswith(".r"):
                reset = int(ln.split()[1], 2) if len(ln.split()) > 1 else None
            elif ln and ln[0] in "01-":
                f = ln.split()
                a, b = int(f[1], 2), int(f[2], 2)
                edges.add((a, b))
                states |= {a, b}
        if crash and not edges:
            return {"status": "tool error", "why": "crashed while writing this FSM: " + crash}
        out = {"status": "found", "edges": sorted(edges), "states": sorted(states), "reset": reset, "names": "values"}
        if crash:
            out["why"] = "crashed after writing this FSM: " + crash
        return out
    if crash:
        return {"status": "tool error", "why": crash}
    return {"status": "not detected", "fsms": [p.name for p in work.glob("*.kiss2")][:6]}


PYV_DRIVER = r'''
import json, sys
from pyverilog.dataflow.dataflow_analyzer import VerilogDataflowAnalyzer
from pyverilog.dataflow.optimizer import VerilogDataflowOptimizer
from pyverilog.controlflow.controlflow_analyzer import VerilogControlflowAnalyzer
files, top, sig, incs = json.loads(sys.argv[1]), sys.argv[2], sys.argv[3], json.loads(sys.argv[4])
an = VerilogDataflowAnalyzer(files, top, preprocess_include=incs, preprocess_define=["SYNTHESIS", "YOSYS"])
an.generate()
terms, binds = an.getTerms(), an.getBinddict()
op = VerilogDataflowOptimizer(terms, binds)
op.resolveConstant()
ca = VerilogControlflowAnalyzer(top, terms, binds, op.getResolvedTerms(), op.getResolvedBinddict(), op.getConstlist(), tuple(sig.split(",")))
fsms = ca.getFiniteStateMachines()
out = {}
for name, fsm in fsms.items():
    edges = []
    for src, conds in fsm.fsm.items():
        for cond, dst in conds.items():
            edges.append([int(src), int(dst)])
    out[str(name)] = edges
print("X5PYV" + json.dumps(out))
'''


def pyverilog_fsm(spec, cert, work):
    """Pyverilog's control-flow analyzer: dataflow, constant folding, state transitions."""
    if not Path(PYV).exists():
        return {"status": "not installed"}
    work.mkdir(parents=True, exist_ok=True)
    (work / "pyv.py").write_text(PYV_DRIVER)
    mod = cert["scope"]["module"]
    sig = cert["observation"][0]["signal"]
    incs = sorted({str(Path(f).parent) for f in spec["files"]} | set(spec.get("include_dirs") or []))
    # Pyverilog reads Verilog-2001 only; SystemVerilog goes through sv2v first, as its users do
    files = order(spec, cert)
    if SV2V.exists():
        rc, log = sh([str(SV2V), "-DSYNTHESIS", "-DYOSYS", *["-I" + d for d in incs], "-w", str(work / "sv2v_out.v"), *files], work, timeout=300)
        if rc == 0 and (work / "sv2v_out.v").exists():
            files = [str(work / "sv2v_out.v")]
        else:
            (work / "sv2v.log").write_text(log)
    alts = [sig] + [re.sub(r"_reg$", "_next", sig)] if sig.endswith("_reg") else [sig]
    rc, log = sh([PYV, "pyv.py", json.dumps(files), mod, ",".join(alts), json.dumps(incs)], work, timeout=900)
    (work / "pyverilog.log").write_text(log)
    m = re.search(r"X5PYV(\{.*\})", log)
    if not m:
        return {"status": "tool error", "why": ("timeout" if rc == 124 else (log.strip().splitlines() or ["?"])[-1][:160])}
    got = json.loads(m.group(1))
    key = next((k for k in got if got[k] and same_fsm(k.split(".")[-1], sig)), None)
    if key is None:
        return {"status": "not detected"}
    edges = {tuple(e) for e in got[key]}
    return {"status": "found", "edges": sorted(edges), "states": sorted({x for e in edges for x in e}), "reset": None, "names": "values"}


TEROS_DRIVER = r'''
const path = require("path");
const fs = require("fs");
require(path.join(process.argv[2], "node_modules", "ts-node")).register({ transpileOnly: true, compilerOptions: { module: "commonjs" } });
const { Paser_fsm_verilog } = require(path.join(process.argv[2], "src/colibri/parser/ts_verilog/fsm.ts"));
(async () => {
  const p = new Paser_fsm_verilog("!", undefined);
  await p.init();
  const code = fs.readFileSync(process.argv[3], "utf8");
  const r = await p.get_svg_sm(code, "!");
  console.log("X5TER" + JSON.stringify(r.stm || r.structure || []));
})().catch(e => { console.log("X5ERR " + e); });
'''


def teroshdl_fsm(spec, cert, work):
    """TerosHDL's state machine viewer (colibri, tree-sitter), headless, on the module's own file."""
    if not (TEROS / "node_modules").exists():
        return {"status": "not installed"}
    work.mkdir(parents=True, exist_ok=True)
    (work / "teros.js").write_text(TEROS_DRIVER)
    src = module_file(spec, cert["scope"]["module"])
    rc, log = sh([NODE, str(work / "teros.js"), str(TEROS), src], TEROS, timeout=300)
    (work / "teros.log").write_text(log)
    m = re.search(r"X5TER(.*)", log)
    if not m:
        return {"status": "tool error", "why": (log.strip().splitlines() or ["?"])[-1][:160]}
    sig = cert["observation"][0]["signal"]
    stm = next((s for s in json.loads(m.group(1)) if same_fsm(s.get("state_variable_name", ""), sig)), None)
    if stm is None:
        return {"status": "not detected"}
    consts = constants(Path(src).read_text(errors="replace"))
    edges, states, unres = set(), set(), set()
    for st in stm.get("states", []):
        a = value_of(st["name"], consts)
        if a is None:
            unres.add(st["name"])
            continue
        states.add(a)
        for t in st.get("transitions", []):
            b = value_of(t["destination"], consts)
            if b is None:
                unres.add(t["destination"])
                continue
            edges.add((a, b))
            states.add(b)
    return {"status": "found", "edges": sorted(edges), "states": sorted(states), "reset": None, "names": "constants", "unresolved": sorted(unres)}


def verilator_fsm(spec, cert, work):
    """Verilator's --coverage-fsm (5.048 and later): FSM states and arcs as coverage points."""
    if not VERILATOR.exists():
        return {"status": "not installed"}
    work.mkdir(parents=True, exist_ok=True)
    mod = cert["scope"]["module"]
    (work / "x5_tb.sv").write_text("module x5_tb; initial $finish; endmodule\n")
    incs = ["-I" + d for d in sorted({str(Path(f).parent) for f in spec["files"]} | set(spec.get("include_dirs") or []))]
    cmd = [str(VERILATOR), "--binary", "--coverage-fsm", "-Wno-fatal", "-Wno-lint", "-Wno-style", "-DSYNTHESIS", "-DYOSYS", "--top-module", mod,
           *incs, *order(spec, cert)]
    rc, log = sh(cmd, work, timeout=900)
    (work / "verilator.log").write_text(log)
    exe = work / "obj_dir" / f"V{mod}"
    if rc != 0 or not exe.exists():
        return {"status": "tool error", "why": (log.strip().splitlines() or ["?"])[-1][:160]}
    sh([str(exe)], work, timeout=120)
    cov = work / "coverage.dat"
    if not cov.exists():
        return {"status": "tool error", "why": "no coverage.dat"}
    text = cov.read_text(errors="replace")
    sig = cert["observation"][0]["signal"]
    consts = constants(Path(module_file(spec, mod)).read_text(errors="replace"))
    edges, states, unres = set(), set(), set()
    for line in text.splitlines():
        if not line.startswith("C '"):
            continue
        # each point is \x01key\x02value pairs: t (fsm_arc / fsm_state), Fv the state variable,
        # Ff and Ft the source and target state as written in the RTL
        f = dict(kv.split("\x02", 1) for kv in line[3:line.rindex("'")].split("\x01") if "\x02" in kv)
        if f.get("t") not in ("fsm_arc", "fsm_state") or f.get("Fv", "").split(".")[-1] != sig:
            continue
        if f["t"] == "fsm_state":
            v = value_of(f.get("Ft", ""), consts)
            if v is None:
                unres.add(f.get("Ft"))
            else:
                states.add(v)
            continue
        a, b = value_of(f.get("Ff", ""), consts), value_of(f.get("Ft", ""), consts)
        if a is None or b is None:
            unres |= {f.get("Ff"), f.get("Ft")}
            continue
        edges.add((a, b))
        states |= {a, b}
    if not edges and not states:
        return {"status": "not detected"}
    return {"status": "found", "edges": sorted(edges), "states": sorted(states), "reset": None, "names": "constants", "unresolved": sorted(unres)}


# ---- scoring ---------------------------------------------------------------------------------------
def score(cert, tool):
    E = {(e["src"], e["dst"]) for e in cert["edges"]}
    W = {(e["src"], e["dst"]) for e in cert["edges"] if e["status"] == "witnessed"}
    S = {s["value"] for s in cert["states"]}
    entry = {s["value"] for s in cert["states"] if s.get("entry")}
    exact = cert["completeness"]["status"] == "proven"
    if tool.get("status") != "found":
        return {"status": tool.get("status"), "missed": len({p for p in W if p[0] != p[1]}), "extra": 0}
    T = {tuple(e) for e in tool["edges"]}
    ns = lambda X: {p for p in X if p[0] != p[1]}  # noqa: E731
    into_reset = {p for p in ns(T) - E if p[1] in entry}
    extra = sorted(ns(T) - E - into_reset) if exact else []
    missed = sorted(ns(W) - T)
    return {"status": "found", "edges": len(ns(T)), "extra": len(extra), "extra_edges": [list(p) for p in extra], "missed": len(missed),
            "missed_edges": [list(p) for p in missed], "into_reset_not_counted": len(into_reset),
            "unreachable_states": sorted(set(tool["states"]) - S), "self_loops_drawn": len(T - ns(T)), "self_loops_real": len(W - ns(W)),
            "exact": not extra and not missed, "unresolved": tool.get("unresolved", [])}


def versions():
    v = {}
    for t, cmd, pat in (("yosys", [YOSYS["yosys"], "-V"], r"Yosys (\S+)"), ("yosys_new", [YOSYS["yosys_new"], "-V"], r"Yosys (\S+)"),
                        ("verilator", [str(VERILATOR), "--version"], r"Verilator (\S+)"), ("pyverilog", [PYV, "-c", "import pyverilog;print('v'+pyverilog.__version__)"], r"v(\S+)")):
        try:
            rc, log = sh(cmd, ".", timeout=60)
            m = re.search(pat, log)
            v[t] = m.group(1) if m else None
        except OSError:
            v[t] = None
    try:
        v["teroshdl"] = json.loads((TEROS / "package.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        v["teroshdl"] = None
    return v


def main(argv):
    out, work = Path(argv[1]), Path(argv[2]).resolve()
    tools = (argv[argv.index("--tools") + 1].split(",") if "--tools" in argv else ["yosys", "yosys_new", "pyverilog", "teroshdl", "verilator"])
    if (out / "audit.json").exists():
        listing = json.loads((out / "audit.json").read_text())["rows"]
    else:  # before the audit: the certificates themselves (the audit is what makes them count)
        listing = []
        for c in sorted(out.glob("*/*/cert.json")):
            x = json.loads(c.read_text())
            listing.append({"dir": str(c.parent), "id": x["id"], "design": x["design"],
                            "undetermined": sum(e["status"] == "undetermined" for e in x["edges"]),
                            "model_witness": sum(e["status"] == "model-witness" for e in x["edges"])})
    rows = []
    for r in listing:
        d = Path(r["dir"])
        cert, spec = json.loads((d / "cert.json").read_text()), json.loads((d / "spec.json").read_text())
        ob = cert["observation"]
        row = {"id": r["id"], "design": r["design"], "edges": len(cert["edges"]), "cert_sha": hashlib.sha256((d / "cert.json").read_bytes()).hexdigest()[:16],
               "real_edges_no_self": sum(1 for e in cert["edges"] if e["status"] == "witnessed" and e["src"] != e["dst"]),
               "exact": r["undetermined"] == 0 and r["model_witness"] == 0, "tools": {}}
        if len(ob) != 1 or ob[0]["width"] < 2:
            row["skip"] = "not one state register: " + ("a 1-bit flag" if len(ob) == 1 else f"{len(ob)} signals together")
            rows.append(row)
            continue
        wd = work / r["design"] / r["id"].replace("/", "_").replace("@", "_")
        for t in tools:
            try:
                got = (yosys_fsm(spec, cert, wd / t, t) if t.startswith("yosys") else
                       pyverilog_fsm(spec, cert, wd / t) if t == "pyverilog" else
                       teroshdl_fsm(spec, cert, wd / t) if t == "teroshdl" else verilator_fsm(spec, cert, wd / t))
            except Exception as ex:  # noqa: BLE001
                got = {"status": "tool error", "why": repr(ex)[:160]}
            row["tools"][t] = dict(score(cert, got), why=got.get("why"))
            print(r["id"], t, row["tools"][t]["status"], "extra", row["tools"][t].get("extra"), "missed", row["tools"][t].get("missed"), flush=True)
        l1 = cert.get("l1_compare")
        if l1:
            row["tools"]["x4"] = {"status": "found", "extra": len(l1.get("l1_only", [])), "missed": len(l1.get("proof_only", []))}
        rows.append(row)
    (work / "bench.json").write_text(json.dumps({"tools": tools, "versions": versions(), "rows": rows}, indent=1))
    print("wrote", work / "bench.json")


if __name__ == "__main__":
    main(sys.argv)
