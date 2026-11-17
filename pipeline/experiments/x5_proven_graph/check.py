"""x5 independent certificate checker. Shares no encoding with prove.py and does not import z3.

    python check.py SPEC.json CERT.json WORK

Given only the RTL and a certificate it re-establishes every claim with other tools:
  * witnessed edges: the certificate's input traces are simulated again in Icarus Verilog and the
    observed pair must appear at the stated step;
  * completeness: the edge set is written as a Verilog monitor (previous observation, current
    observation, allowed pairs), wired to the observed signals after `flatten`, and Yosys's own
    SAT pass (MiniSat, SatGen encoding) proves `ok` by temporal induction, or by BMC to the
    certificate's depth when the certificate only claims a bound.
The reset protocol is part of the property (`ok` is only required while the protocol has been
followed), so no assume cells are needed.
"""
import json
import re
import shutil
import sys
from pathlib import Path

import prove as P  # sh(), top_first(), inject_sources(), _defs(), _ident(): text and process helpers only


def support(cert):
    """The edge set whose completeness is to be proved: the certificate's own, or the finer one it
    carries (more signals observed). The finer set is not trusted: it is proved like any other, and
    here every one of its pairs must project onto an edge of the certificate.
    -> (observation, width, pairs), or None when it does not."""
    keep, s = cert["observation"], cert["completeness"].get("support")
    if cert["width"] != sum(o["width"] for o in keep):
        return None
    if not s:
        return keep, cert["width"], [(e["src"], e["dst"]) for e in cert["edges"]]
    ob, W = s["observation"], s["width"]
    if ob[:len(keep)] != keep or W != sum(o["width"] for o in ob):
        return None
    have, sh = {(e["src"], e["dst"]) for e in cert["edges"]}, W - cert["width"]
    if any((a >> sh, b >> sh) not in have for a, b in s["pairs"]):
        return None
    return ob, W, [tuple(p) for p in s["pairs"]]


def monitor(cert, W, pairs):
    R = cert["assumptions"]["reset_cycles"]
    by = {}
    for a, b in pairs:
        by.setdefault(a, []).append(b)
    L = [f"module x5_mon(input x5_clk, (* keep *) input [{W - 1}:0] obs, input rst_act, (* keep *) output ok);",
         f"  reg [15:0] c = 0; reg viol = 0; reg pv = 0; reg [{W - 1}:0] prev = 0; reg pair;",
         f"  wire inr = c < {R};",
         "  wire v = viol | (inr ? !rst_act : rst_act);" if cert["assumptions"]["reset"] else "  wire v = 1'b0;",
         f"  always @({'negedge' if cert['assumptions']['clock']['edge'] == 'negedge' else 'posedge'} x5_clk) begin",
         "    viol <= v; if (inr) c <= c + 1; prev <= obs; pv <= !inr;", "  end",
         "  always @* begin", "    pair = 1'b0;", "    case (prev)"]
    for a, bs in sorted(by.items()):
        L.append(f"      {W}'d{a}: pair = " + " | ".join(f"(obs == {W}'d{b})" for b in sorted(set(bs))) + ";")
    L += ["      default: pair = 1'b0;", "    endcase", "  end", "  assign ok = v | !pv | inr | pair;", "endmodule"]
    return "\n".join(L)


def completeness(spec, cert, work, timeout=900, maxsteps=10):
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    top, A = spec["top"], cert["assumptions"]
    sup = support(cert)
    if sup is None:
        return {"result": "failed", "engine": "projection", "why": "the supporting edge set does not project into the certificate's edges"}
    sob, sW, pairs = sup
    files = [str(f) for f in spec["files"]]
    incs = list(spec.get("include_dirs") or []) + sorted({str(Path(f).parent) for f in files})
    spec = dict(spec, include_dirs=incs)
    act = " & ".join(("(~" if r["active_low"] else "(") + r["port"] + ")" for r in A["reset"]) or "1'b0"
    inst = f"  (* keep *) x5_mon x5_mon (.x5_clk({A['clock']['port']}), .rst_act({act}));"
    files = P.usable_files(spec, files, work / "files")[0]
    srcs = P.inject_sources(files, work, {cert["scope"]["module"]: inst})
    scoped = bool(cert["scope"]["instance"])
    (work / "x5_mon.v").write_text(monitor(cert, sW, pairs))  # the injected instance needs its module to elaborate
    derived = P.resolve_scope(dict(spec, scope=cert["scope"]["instance"]), srcs + [str(work / "x5_mon.v")], work / "scope")[0]
    cut = f"hierarchy -check -top {top}\n" + (f"hierarchy -top {derived}\nrename -top x5_scope\n" if scoped else "")
    design_top, top = top, ("x5_scope" if scoped else top)
    obs = ",".join(chr(92) + o["signal"] for o in sob)  # first token is the MSB
    proven = cert["completeness"]["status"] == "proven"
    depth = A["reset_cycles"] + cert["completeness"]["depth"] + 1
    goal = (f"sat -tempinduct -prove x5_mon.ok 1 -maxsteps {maxsteps} -timeout {timeout}" if proven
            else f"sat -seq {depth} -prove x5_mon.ok 1 -timeout {timeout}")
    log = ""
    # only the order the certificate states; certificates older than that field get the two orders tried in turn
    orders = [ordered(cert, srcs, design_top)] if cert["assumptions"].get("source_order") else [srcs, P.top_first(srcs, design_top)]
    for order in orders:
        # Cone of influence: the design's outputs stop being ports, so `opt_clean` removes every cell
        # that feeds neither the monitor (kept) nor anything it depends on, a FIFO's data words say.
        # Logic outside the fan-in of `ok` cannot change `ok`, so the proof is about the same thing.
        ys = (f"read_verilog -sv {' '.join(P._defs(spec))} {' '.join(order)} x5_mon.v\n" + cut +
              f"prep -flatten -top {top}\ncd {top}\nconnect -set {chr(92)}x5_mon.obs {obs}\ncd ..\n"
              "async2sync\ndffunmap\nmemory_map\nsetundef -undriven -anyseq\nsetundef -anyseq\nopt_clean\n"
              f"cd {top}\ntee -q -o cone_before.txt select -count t:*\ndelete -port o:*\nopt_clean\n"
              f"tee -q -o cone_after.txt select -count t:*\n{goal}\n")
        (work / "check.ys").write_text(ys)
        rc, log = P.sh([P.YOSYS, "-s", "check.ys"], cwd=work, timeout=timeout + 120)
        (work / "check.log").write_text(log)
        if "Executing SAT pass" in log:
            break
    if "Executing SAT pass" in log and "End of script" not in log and "Induction step proven: SUCCESS!" not in log:
        # the solver was stopped from outside (out of memory, time limit): no verdict at all
        return {"result": "aborted", "engine": "yosys sat", "why": "yosys did not finish: " + ("time limit" if rc == 124 else f"exit status {rc}")}
    if "Interrupted SAT solver: TIMEOUT!" in log:
        return {"result": "aborted", "engine": "yosys sat", "why": f"solver time limit of {timeout} s"}
    # A verdict is one of the conclusions Yosys prints. Anything else (an error before the solver ran,
    # an unknown ending) is no verdict, so a broken run is never counted as a rejection.
    marks = ("Induction step proven: SUCCESS!", "model found for base case", "maximum number of time steps",
             "no model found: SUCCESS!", "model found: FAIL")
    if not any(x in log for x in marks):
        return {"result": "aborted", "engine": "yosys sat", "why": "no verdict: " + (log.strip().splitlines() or ["?"])[-1][:160]}
    if proven:
        if "Induction step proven: SUCCESS!" in log:
            k = re.findall(r"Trying induction with length (\d+)", log)
            return {"result": "proven", "engine": "yosys sat tempinduct", "step": int(k[-1]) if k else None}
        why = ("base case fails" if "model found for base case" in log else
               "not inductive within maxsteps" if "maximum number of time steps" in log else (log.strip().splitlines() or ["?"])[-1][:160])
        return {"result": "failed", "engine": "yosys sat tempinduct", "why": why}
    if "no model found: SUCCESS!" in log:
        return {"result": "bounded-ok", "engine": "yosys sat bmc", "depth": depth}
    return {"result": "failed", "engine": "yosys sat bmc",
            "why": "counterexample" if "model found: FAIL" in log else (log.strip().splitlines() or ["?"])[-1][:160]}


def ordered(cert, files, top):
    """The source files in the order the certificate states. Simulator and proof both use exactly this
    order, so they cannot end up with two configurations of the design."""
    return P.top_first(files, top) if cert["assumptions"].get("source_order") == "top module's file first" else list(files)


class _K:  # the few fields replay() needs, rebuilt from the certificate alone
    def __init__(self, spec, cert):
        files = [str(f) for f in spec["files"]]
        incs = list(spec.get("include_dirs") or []) + sorted({str(Path(f).parent) for f in files})
        t0 = cert["traces"][0] if cert["traces"] else {"inputs": {}, "init_regs": {}}
        self.obs = [(o["signal"], o["width"]) for o in cert["observation"]]
        self.W, self.R = cert["width"], cert["assumptions"]["reset_cycles"]
        self.ins = list(cert.get("widths", {}).get("inputs") or t0["inputs"])  # the declared inputs, not what one trace happens to list
        self.m = type("M", (), {})()
        self.m.top, self.m.files, self.m.spec = spec["top"], [f for f in files if f not in cert["engine"].get("files_dropped", [])], dict(spec, include_dirs=incs)
        self.m.files = ordered(cert, self.m.files, spec["top"])
        self.m.sim_top, self.m.sim_params = cert["scope"]["module"], cert["scope"]["parameters"]
        self.m.clock, self.m.negedge = cert["assumptions"]["clock"]["port"], cert["assumptions"]["clock"]["edge"] == "negedge"
        self.m.inputs, self.m.regs = cert.get("widths", {}).get("inputs", {}), cert.get("widths", {}).get("regs", {})
        self.m.mems = cert.get("widths", {}).get("mems", {})


def allowed(cert, tr):
    """Is the trace an execution the certificate's assumptions allow? Every input has a value in every
    cycle, and reset is held for the first reset_cycles cycles and never again. (Its power-up state is
    checked by the simulator: replay() refuses a value where the RTL has an initial value.)"""
    A, n = cert["assumptions"], len(tr.get("obs", []))
    W = cert.get("widths", {}).get("inputs", {})
    if set(tr.get("inputs", {})) != set(W) or any(len(v) != n for v in tr["inputs"].values()):
        return False
    if any(not isinstance(x, int) or not 0 <= x < 2 ** W[p] for p, v in tr["inputs"].items() for x in v):
        return False
    for r in A["reset"]:
        act = 0 if r["active_low"] else 1
        if r["port"] not in tr["inputs"] or any((x == act) != (t < A["reset_cycles"]) for t, x in enumerate(tr["inputs"][r["port"]])):
            return False
    return True


def witnesses(spec, cert, work):
    """Every `witnessed` edge must show up at its step when its trace is simulated again, and the
    trace must be one the assumptions allow."""
    k = _K(spec, cert)
    legal = [allowed(cert, tr) for tr in cert["traces"]]
    idx = [i for i, ok in enumerate(legal) if ok]  # a trace outside the assumptions is not simulated at all
    part, how = P.replay(k, [cert["traces"][i] for i in idx], Path(work) / "replay") if idx else ([], "none")
    rep = None if part is None else [0] * len(legal)
    for j, i in enumerate(idx if part is not None else []):
        rep[i] = part[j]
    bad = []
    for e in cert["edges"]:
        if e["status"] != "witnessed":
            continue
        tr = cert["traces"][e["trace"]] if 0 <= e.get("trace", -1) < len(cert["traces"]) else None
        t = e.get("step", -1)
        if (rep is None or tr is None or not legal[e["trace"]] or t < k.R or t + 1 >= len(tr["obs"])
                or (tr["obs"][t], tr["obs"][t + 1]) != (e["src"], e["dst"]) or rep[e["trace"]] < (t - k.R) + 2):
            bad.append([e["src"], e["dst"]])
    # A replayed trace is a real execution. Every step of it the simulator agreed on must be an edge of
    # the certificate, or the claim that no other transition can happen is false. This needs no solver.
    listed, outside = {(e["src"], e["dst"]) for e in cert["edges"]}, []
    for i, tr in enumerate(cert["traces"]):
        if rep is None or not legal[i]:
            continue
        for t in range(k.R, k.R + rep[i] - 1):
            p = (tr["obs"][t], tr["obs"][t + 1])
            if p not in listed and [i, t, p[0], p[1]] not in outside:
                outside.append([i, t, p[0], p[1]])
    return {"result": "ok" if not bad and not outside else "failed", "mode": how, "unconfirmed": bad,
            "traces_outside_assumptions": [i for i, x in enumerate(legal) if not x],
            "replayed_pairs_not_listed": outside[:20]}


def check(spec, cert, work, timeout=900, skip_proof_when_witnesses_fail=False, maxsteps=10):
    """maxsteps bounds the induction of the second engine. A smaller bound can only turn an
    acceptance into a rejection, never the other way, so a caller may pass one to limit cost."""
    work = Path(work).resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    # A certificate the checker cannot even read is rejected, with the reason. It never passes by accident
    # and it never takes the checker down.
    try:
        sv = {s["value"] for s in cert["states"]}
        form = (all(e["src"] in sv and e["dst"] in sv and e["status"] in ("witnessed", "model-witness", "undetermined") for e in cert["edges"])
                and len({(e["src"], e["dst"]) for e in cert["edges"]}) == len(cert["edges"])
                and all(isinstance(v, int) and 0 <= v < 2 ** cert["width"] for v in sv))
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "wellformed": False, "witnesses": {"result": "not run"}, "completeness": {"result": "not run"}, "why": "malformed: " + repr(ex)[:200]}
    try:
        w = witnesses(spec, cert, work)
    except Exception as ex:  # noqa: BLE001
        w = {"result": "failed", "why": "malformed: " + repr(ex)[:200], "unconfirmed": []}
    if skip_proof_when_witnesses_fail and w["result"] != "ok":
        c = {"result": "not run", "why": "already rejected by the witness check"}
    else:
        try:
            c = completeness(spec, cert, work / "ind", timeout=timeout, maxsteps=maxsteps)
        except Exception as ex:  # noqa: BLE001
            c = {"result": "failed", "why": "malformed: " + repr(ex)[:200]}
    return {"ok": form and w["result"] == "ok" and c["result"] in ("proven", "bounded-ok"), "wellformed": form, "witnesses": w, "completeness": c}


if __name__ == "__main__":
    spec, cert = json.loads(Path(sys.argv[1]).read_text()), json.loads(Path(sys.argv[2]).read_text())
    print(json.dumps(check(spec, cert, sys.argv[3])))
