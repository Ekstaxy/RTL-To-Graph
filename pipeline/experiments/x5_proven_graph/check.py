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


MON_REGS = ("c", "prev", "pv", "viol")  # the monitor's own registers an invariant may name


def lemma_signals(inv):
    """The design signals an invariant names, in the order they are wired to the monitor's `lem`
    input (the first is the most significant part), with their widths as the certificate states them.
    A wrong width makes Yosys refuse the wiring, which is no verdict; it can never pass a proof."""
    used = sorted({n for cube in inv["blocked"] for where, n, _, _ in cube if where == "design"})
    return [(n, int(inv["signals"][n])) for n in used]


def monitor(cert, W, pairs, inv=None, bad=False):
    """inv: an inductive invariant offered by the certificate, as cubes no reachable state matches
    after the first cycle. It is a hint, not a claim: `ok` then also requires the invariant, and the
    induction must prove both. A wrong or useless invariant can only make the proof fail."""
    R = cert["assumptions"]["reset_cycles"]
    by = {}
    for a, b in pairs:
        by.setdefault(a, []).append(b)
    sigs = lemma_signals(inv) if inv else []
    nlem = sum(w for _, w in sigs)
    ports = f"input x5_clk, (* keep *) input [{W - 1}:0] obs, input rst_act, (* keep *) output ok"
    if sigs:
        ports += f", (* keep *) input [{nlem - 1}:0] lem"
    if bad:
        ports += ", (* keep *) output bad"
    L = [f"module x5_mon({ports});",
         f"  reg [15:0] c = 0; reg viol = 0; reg pv = 0; reg [{W - 1}:0] prev = 0; reg pair;",
         f"  wire inr = c < {R};",
         "  wire v = viol | (inr ? !rst_act : rst_act);" if cert["assumptions"]["reset"] else "  wire v = 1'b0;",
         f"  always @({'negedge' if cert['assumptions']['clock']['edge'] == 'negedge' else 'posedge'} x5_clk) begin",
         "    viol <= v; if (inr) c <= c + 1; prev <= obs; pv <= !inr;", "  end",
         "  always @* begin", "    pair = 1'b0;", "    case (prev)"]
    for a, bs in sorted(by.items()):
        L.append(f"      {W}'d{a}: pair = " + " | ".join(f"(obs == {W}'d{b})" for b in sorted(set(bs))) + ";")
    L += ["      default: pair = 1'b0;", "    endcase", "  end"]
    if inv:
        off, low = {}, nlem
        for n, w in sigs:
            low -= w
            off[n] = (low, w)
        def lit(where, n, b, v):
            if where == "design" and not 0 <= b < off[n][1]:
                raise ValueError(f"bit {b} of {n} is outside its stated width")
            return f"(lem[{off[n][0] + b}] == 1'b{v})" if where == "design" else f"({n}[{b}] == 1'b{v})"
        cubes = [" & ".join(lit(*x) for x in cube) or "1'b1" for cube in inv["blocked"]]
        L += ["  reg x5_first = 1;",
              f"  always @({'negedge' if cert['assumptions']['clock']['edge'] == 'negedge' else 'posedge'} x5_clk) x5_first <= 0;",
              # in the first cycle only the monitor's own initial values are known; afterwards no blocked cube holds
              f"  wire inv_ok = x5_first ? (c == 0 && !viol && !pv && prev == 0) : !({' | '.join(f'({x})' for x in cubes) or '1' + chr(39) + 'b0'});",
              "  assign ok = (v | !pv | inr | pair) & inv_ok;"]
    else:
        L += ["  assign ok = v | !pv | inr | pair;"]
    if bad:
        L += ["  assign bad = !ok;"]
    L += ["endmodule"]
    return "\n".join(L)


def _sig(n, b=None):
    return chr(92) + n + ("" if b is None else f" [{b}]")


def design(spec, cert, work, sob, sW, pairs, inv=None, bad=False):
    """The design with the monitor wired in, as Yosys reads it for a proof: one script prefix per source
    order to try, each ending with the flattened, synchronous, memory-free netlist of module `top`.
    -> (prefixes, top). The prover's PDR builds its AIGER from exactly this netlist."""
    top, A = spec["top"], cert["assumptions"]
    files = [str(f) for f in spec["files"]]
    incs = list(spec.get("include_dirs") or []) + sorted({str(Path(f).parent) for f in files})
    spec = dict(spec, include_dirs=incs)
    act = " & ".join(("(~" if r["active_low"] else "(") + r["port"] + ")" for r in A["reset"]) or "1'b0"
    inst = f"  (* keep *) x5_mon x5_mon (.x5_clk({A['clock']['port']}), .rst_act({act}));"
    files = P.usable_files(spec, files, work / "files")[0]
    srcs = P.inject_sources(files, work, {cert["scope"]["module"]: inst})
    scoped = bool(cert["scope"]["instance"])
    (work / "x5_mon.v").write_text(monitor(cert, sW, pairs, inv=inv, bad=bad))  # the injected instance needs its module to elaborate
    derived = P.resolve_scope(dict(spec, scope=cert["scope"]["instance"]), srcs + [str(work / "x5_mon.v")], work / "scope")[0]
    cut = f"hierarchy -check -top {top}\n" + (f"hierarchy -top {derived}\nrename -top x5_scope\n" if scoped else "")
    design_top, top = top, ("x5_scope" if scoped else top)
    wire = f"connect -set {chr(92)}x5_mon.obs " + ",".join(_sig(o["signal"]) for o in sob) + "\n"  # first token is the MSB
    if inv and lemma_signals(inv):
        wire += f"connect -set {chr(92)}x5_mon.lem " + ",".join(_sig(n) for n, _ in lemma_signals(inv)) + "\n"
    # only the order the certificate states; certificates older than that field get the two orders tried in turn
    orders = [ordered(cert, srcs, design_top)] if cert["assumptions"].get("source_order") else [srcs, P.top_first(srcs, design_top)]
    return [(f"read_verilog -sv {' '.join(P._defs(spec))} {' '.join(order)} x5_mon.v\n" + cut +
             f"prep -flatten -top {top}\ncd {top}\n{wire}cd ..\n"
             "async2sync\ndffunmap\nmemory_map\nsetundef -undriven -anyseq\nsetundef -anyseq\nopt_clean\n") for order in orders], top


def completeness(spec, cert, work, timeout=900, maxsteps=16):
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    A = cert["assumptions"]
    inv = cert["completeness"].get("invariant")
    if inv:
        # An invariant is stated over the certificate's own observation: the edges are proved directly.
        if not isinstance(inv.get("blocked"), list) or not isinstance(inv.get("signals"), dict) or any(
                not (isinstance(x, list) and len(x) == 4 and x[0] in ("design", "monitor") and isinstance(x[2], int) and x[3] in (0, 1)
                     and (x[1] in inv["signals"] if x[0] == "design" else x[1] in MON_REGS) and re.fullmatch(r"[A-Za-z_][\w$.\[\]]*", str(x[1])))
                for cube in inv["blocked"] for x in cube):
            return {"result": "failed", "engine": "invariant", "why": "malformed invariant"}
        sob, sW, pairs = cert["observation"], cert["width"], [(e["src"], e["dst"]) for e in cert["edges"]]
    else:
        sup = support(cert)
        if sup is None:
            return {"result": "failed", "engine": "projection", "why": "the supporting edge set does not project into the certificate's edges"}
        sob, sW, pairs = sup
    prefixes, top = design(spec, cert, work, sob, sW, pairs, inv=inv)
    proven = cert["completeness"]["status"] == "proven"
    depth = A["reset_cycles"] + cert["completeness"]["depth"] + 1
    goal = (f"sat -tempinduct -prove x5_mon.ok 1 -maxsteps {maxsteps} -timeout {timeout}" if proven
            else f"sat -seq {depth} -prove x5_mon.ok 1 -timeout {timeout}")
    log = ""
    for pre in prefixes:
        # Cone of influence: the design's outputs stop being ports, so `opt_clean` removes every cell
        # that feeds neither the monitor (kept) nor anything it depends on, a FIFO's data words say.
        # Logic outside the fan-in of `ok` cannot change `ok`, so the proof is about the same thing.
        ys = (pre + f"cd {top}\ntee -q -o cone_before.txt select -count t:*\ndelete -port o:*\nopt_clean\n"
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
            out = {"result": "proven", "engine": "yosys sat tempinduct", "step": int(k[-1]) if k else None}
            if inv:
                out.update(engine="yosys sat tempinduct, with the certificate's invariant", invariant_cubes=len(inv["blocked"]))
            return out
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


def own_state(spec, cert, work):
    """Every register and memory of the design under the hierarchical name the simulator knows it
    by, from the checker's own Yosys run (prove.hier_state: elaborated without flattening, each
    module's registers under its instance path). The replay makes all of them defined at power-up
    and watches them for unknown bits; taking the list from the certificate would let a certificate
    leave a register unknown and the simulator's x rules decide.
    -> (registers {name: width}, memories {name: {"size", "width"}})"""
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    prefixes, top = design(spec, cert, work, cert["observation"], cert["width"], [])
    for pre in prefixes:
        regs, mems = P.hier_state(pre.split("prep -flatten")[0], top, work, timeout=900)  # where design() wrote x5_mon.v
        if regs is not None:
            return regs, mems
    raise RuntimeError("yosys could not list the design's registers")


def witnesses(spec, cert, work):
    """Every `witnessed` edge must show up at its step when its trace is simulated again, and the
    trace must be one the assumptions allow."""
    k = _K(spec, cert)
    own_regs, own_mems = own_state(spec, cert, Path(work) / "state")
    k.m.fill_regs, k.m.fill_mems = own_regs, own_mems  # the certificate's names stay in k.m.regs, for its power-up values
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
    two = str(how).startswith("two-valued") or not any(e["status"] == "witnessed" for e in cert["edges"])
    return {"result": "ok" if not bad and not outside and two else "failed", "mode": how, "unconfirmed": bad,
            "state": {"registers": len(own_regs), "memories": len(own_mems)},
            "traces_outside_assumptions": [i for i, x in enumerate(legal) if not x],
            "replayed_pairs_not_listed": outside[:20]}


def observe(k, tr, work, timeout=900):
    """Simulate one input sequence from power-up, two-valued (see prove._fill), with the trace's own
    power-up values. -> list of observations as bit strings, None from the first unknown bit on."""
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    head = P._tb_head(k)
    if head is None:
        return None
    L, cat, win, idle, act = head
    n = len(next(iter(tr["inputs"].values()))) if tr["inputs"] else 0
    digits = (max(win, 1) + 3) // 4
    (work / "ref.hex").write_text("".join(f"{P._pack(k, tr, t):0{digits}x}\n" for t in range(n)))
    dec, fill = P._fill(k.m)
    L += dec + [f"  reg [{max(win, 1) - 1}:0] vec [0:{max(n, 1) - 1}];", "  integer x5_i;", "  reg x5_bad = 0;", "  initial begin",
                '    $readmemh("ref.hex", vec); x5_xs = 0; x5_xm = 0;', "    #1;"]
    soft = []
    for ln in P._deposits(k.m, tr) + fill:
        soft.append(len(L))
        L.append(ln)
    L += ['    if (x5_bad) $display("X5BAD;");', f"    for (x5_i = 0; x5_i < {n}; x5_i = x5_i + 1) begin", "      cur = vec[x5_i];", "      #4;"]
    for ln in P._xcheck(k.m):
        soft.append(len(L))
        L.append(ln)
    L += [f'      $display("X5O%0d:%b:%0d;", x5_i, {cat}, x5_xs + x5_xm); #1 x5_clk = {act}; #5 x5_clk = {idle};', "    end", "    $finish;", "  end", "endmodule"]
    ok, _, log = P._compile(k.m, work, work / "x5_ref.sv", L, soft, "ref.vvp", timeout)
    if not ok:
        return None
    rc, log = P.sh(["vvp", "-n", "ref.vvp"], cwd=work, timeout=timeout)
    if "X5BAD;" in log:
        return None
    got = {int(t): (o, x) for t, o, x in re.findall(r"X5O(\d+):([01xzXZ]+):(\d+);", log)}
    out, dead = [], False
    for t in range(n):
        o, x = got.get(t, (None, "1"))
        dead = dead or x != "0" or o is None or not set(o) <= {"0", "1"}
        out.append(None if dead else o)
    return out


def refute(spec, cert, work, seconds=120):
    """After the induction failed: look for a concrete execution that takes an edge the certificate
    does not list. ABC searches the checker's own netlist (PDR, which also finds deep
    counterexamples), and the input sequence and power-up values it returns are simulated in Icarus
    Verilog, two-valued. Only the simulator's run counts: a pair it shows that is not listed refutes
    the certificate. Finding nothing proves nothing either way; the certificate stays rejected."""
    work = Path(work).resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    listed = {(e["src"], e["dst"]) for e in cert["edges"]}
    prefixes, top = design(spec, cert, work, cert["observation"], cert["width"], sorted(listed), bad=True)
    ys = (prefixes[0] + f"cd {top}\ndelete -port o:*\nexpose x5_mon.bad\nopt_clean\ncd ..\n"
          "techmap\nopt_clean\naigmap\nopt_clean\nwrite_aiger -zinit -map aig.map x.aig\n")
    (work / "ref.ys").write_text(ys)
    rc, log = P.sh([P.YOSYS, "-q", "-s", "ref.ys"], cwd=work, timeout=900)
    if rc != 0:
        return {"result": "none", "why": "no AIGER: " + (log.strip().splitlines() or ["?"])[-1][:120]}
    rc, log = P.sh(["yosys-abc", "-c", f"read_aiger x.aig; pdr -T {int(seconds)}; write_cex -n cex.txt"], cwd=work, timeout=seconds + 120)
    m = re.search(r"was asserted in frame (\d+)", log)
    if not m or not (work / "cex.txt").exists():
        return {"result": "none", "why": "no counterexample within " + str(seconds) + " s"}
    pin, ini = {}, {}
    for ln in (work / "aig.map").read_text().splitlines():
        f = ln.split()
        if f[0] == "input":
            pin[int(f[1])] = (int(f[2]), f[3])
        elif f[0] == "init":
            ini.setdefault(int(f[1]), []).append((int(f[2]), f[3]))
    val = {}
    for i, fr, v in re.findall(r"^pi(\d+)@(\d+)=([01])$", (work / "cex.txt").read_text(), re.M):
        val[(int(i), int(fr))] = int(v)
    n = int(m.group(1)) + 1
    W = cert["widths"]["inputs"]
    ins = {p: [0] * n for p in W}
    for (i, fr), v in val.items():
        if i in pin and pin[i][1] in ins and fr < n and v:
            ins[pin[i][1]][fr] |= 1 << pin[i][0]
    k = _K(spec, cert)
    own_regs, own_mems = own_state(spec, cert, work / "state")
    k.m.fill_regs, k.m.fill_mems = own_regs, own_mems
    init = {}
    for i, names in ini.items():
        for b, nm in names:
            if nm in k.m.regs and val.get((i, 0)):
                init[nm] = init.get(nm, 0) | (1 << b)
            elif nm in k.m.regs:
                init.setdefault(nm, 0)
    tr = {"inputs": ins, "init_regs": init, "init_mems": {}}
    seen = observe(k, tr, work / "sim")
    if seen is None:
        return {"result": "none", "why": f"the counterexample of {n} cycles did not simulate"}
    R = cert["assumptions"]["reset_cycles"]
    for t in range(R, n - 1):
        if seen[t] is None or seen[t + 1] is None:
            break
        p = (int(seen[t], 2), int(seen[t + 1], 2))
        if p not in listed:
            return {"result": "refuted", "pair": list(p), "step": t, "cycles": n,
                    "why": f"counterexample replayed: {p[0]}->{p[1]} at cycle {t}, not listed"}
    return {"result": "none", "why": f"the simulator did not reproduce the counterexample of {n} cycles"}


def check(spec, cert, work, timeout=900, skip_proof_when_witnesses_fail=False, maxsteps=16, refute_seconds=60):
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
        if c["result"] == "failed" and str(c.get("engine", "")).startswith("yosys sat") and refute_seconds:
            # the rejection stands either way; a replayed counterexample says why
            try:
                ref = refute(spec, cert, work / "refute", seconds=refute_seconds)
            except Exception as ex:  # noqa: BLE001
                ref = {"result": "none", "why": "error: " + repr(ex)[:160]}
            c = dict(c, refutation=ref, induction=c.get("why"))
            if ref["result"] == "refuted":
                c["why"] = "counterexample replayed in the simulator"
    return {"ok": form and w["result"] == "ok" and c["result"] in ("proven", "bounded-ok"), "wellformed": form, "witnesses": w, "completeness": c}


if __name__ == "__main__":
    spec, cert = json.loads(Path(sys.argv[1]).read_text()), json.loads(Path(sys.argv[2]).read_text())
    print(json.dumps(check(spec, cert, sys.argv[3])))
