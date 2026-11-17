"""x5: proof-carrying state graphs.

The graph is not extracted and then checked; the proof engine computes it. Pick any vector of
observed bits `obs` (a state register, several registers, or injected predicate wires). The design's
transition system is projected onto `obs`:

  W  witness   BMC from the initial condition. Every SAT answer is a concrete trace; every pair
               (obs[t], obs[t+1]) on it becomes a WITNESSED edge. UNSAT at depth d proves that no
               other pair can occur at step d.
  I  induction k-induction from an arbitrary state: if the last k pairs are edges of the graph, so
               is the next one. UNSAT -> the graph is complete forever. A counterexample to
               induction is a pair that is possible from some state nobody proved reachable; it is
               added as an UNDETERMINED edge and the proof is tried again.
  R  replay    every witness trace is run in Icarus Verilog (another front end, another
               simulator). An edge keeps `witnessed` only if the simulator shows the same pair.

Claims carried by the result, each with its evidence:
  * a witnessed edge happens in a real execution (trace, confirmed by replay);
  * an absent edge can never happen (induction proof), or cannot happen within `depth` cycles of
    reset when the induction did not close (`completeness.status`);
  * an undetermined edge is neither: it is drawn differently and never presented as fact.
Nothing here uses the L1 front end: Yosys builds the model, z3 answers, iverilog replays.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import z3

YOSYS = os.environ.get("YOSYS", "yosys")
RESET_RE = re.compile(r"(^|_)(a?rst|a?reset|rstn|resetn|nrst|nreset|aresetn|arstn)(_?n|_?ni|_?i|_?b)?$", re.I)
LOW_RE = re.compile(r"(rstn|resetn|rst_n|reset_n|nrst|nreset|rst_ni|reset_ni|rst_b|reset_b)", re.I)


class Refuse(Exception):
    """The design or the observation is outside what the kernel models exactly. No graph is produced."""


def sh(cmd, cwd=None, timeout=600):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, errors="replace")
        return p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def _defs(spec):
    out = []
    for d in spec.get("defines", []) or []:
        out.append("-D" + d)
    for i in spec.get("include_dirs", []) or []:
        out.append("-I" + str(i))
    return out


def top_first(files, top):
    pat = re.compile(r"^\s*module\s+" + re.escape(top) + r"\b", re.M)
    for f in files:
        try:
            if pat.search(Path(f).read_text(errors="replace")):
                return [f] + [x for x in files if x != f]
        except OSError:
            pass
    return list(files)


def inject_sources(files, work, inject):
    """Copy the sources and add text before `endmodule` of the named modules. {module: verilog}"""
    src = Path(work).resolve() / "src"
    src.mkdir(parents=True, exist_ok=True)
    out, done = [], set()
    for i, f in enumerate(files):
        text = Path(f).read_text(errors="replace")
        masked = re.sub(r"//[^\n]*|/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
        edits = []
        for mod, add in inject.items():
            m = re.search(r"\bmodule\s+" + re.escape(mod) + r"\b", masked)
            if not m:
                continue
            e = re.search(r"\bendmodule\b", masked[m.end():])
            if e:
                edits.append((m.end() + e.start(), add))
                done.add(mod)
        for pos, add in sorted(edits, reverse=True):
            text = text[:pos] + "\n" + add + "\n" + text[pos:]
        p = src / f"{i}_{Path(f).name}"
        p.write_text(text)
        out.append(str(p))
    missing = set(inject) - done
    if missing:
        raise Refuse(f"module not found for injection: {sorted(missing)}")
    return out


def usable_files(spec, files, work, timeout=300):
    """Files of the list that Yosys can read. A file that fails to parse is dropped and the rest is
    tried again; `hierarchy -check` then fails if the dropped file was needed, so nothing the top
    module depends on can go missing silently. -> (files, dropped)"""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    files, dropped, log = list(files), [], ""
    for _ in range(8):
        for order in (files, top_first(files, spec["top"])):
            ys = f"read_verilog -sv {' '.join(_defs(spec))} {' '.join(order)}\nhierarchy -check -top {spec['top']}\n"
            (work / "files.ys").write_text(ys)
            rc, log = sh([YOSYS, "-q", "-s", "files.ys"], cwd=work, timeout=timeout)
            if rc == 0:
                return files, dropped
        bad = [f for f in files if re.search(re.escape(f) + r":\d+: ERROR", log)]
        if not bad:
            break
        files = [f for f in files if f != bad[0]]
        dropped.append(bad[0])
    raise Refuse("yosys cannot build the model: " + (log.strip().splitlines() or ["?"])[-1][:200])


def _param(v):
    v = v.strip()
    m = re.fullmatch(r"(\d+)'([01xz]+)", v)
    return f"{m.group(1)}'b{m.group(2)}" if m else v


def resolve_scope(spec, files, work, timeout=300):
    """Walk the instance path spec["scope"] from the top. -> (yosys module name, source module name,
    {parameter: verilog value}) of the instance, as elaborated inside this design."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    cur, name = spec["top"], spec["top"]
    for i, inst in enumerate(spec.get("scope") or []):
        log = ""
        for order in (files, top_first(files, spec["top"])):
            ys = (f"read_verilog -sv {' '.join(_defs(spec))} {' '.join(order)}\nhierarchy -check -top {spec['top']}\n"
                  f"tee -q -o scope{i}.txt select -list {cur}/c:{inst} %M\n")
            (work / f"scope{i}.ys").write_text(ys)
            rc, log = sh([YOSYS, "-q", "-s", f"scope{i}.ys"], cwd=work, timeout=timeout)
            if rc == 0:
                break
        else:
            raise Refuse("yosys cannot elaborate the design: " + (log.strip().splitlines() or ["?"])[-1][:200])
        lines = [x for x in (work / f"scope{i}.txt").read_text().splitlines() if x.strip()]
        if not lines:
            raise Refuse(f"instance {inst} not found in {cur}")
        cur = lines[0].split("/", 1)[0]
    params = {}
    if spec.get("scope"):
        ys = (f"read_verilog -sv {' '.join(_defs(spec))} {' '.join(top_first(files, spec['top']))}\nhierarchy -check -top {spec['top']}\n"
              f"tee -q -o params.txt dump -n {cur}\n")
        (work / "params.ys").write_text(ys)
        sh([YOSYS, "-q", "-s", "params.ys"], cwd=work, timeout=timeout)
        txt = (work / "params.txt").read_text() if (work / "params.txt").exists() else ""
        m = re.search(r'attribute .hdlname "..([^"]+)"', txt)
        name = m.group(1) if m else cur.split(chr(92))[-1]
        for k, v in re.findall(r"^\s*parameter\s+(?:signed\s+)?.(\S+)\s+(.+)$", txt, re.M):
            params[k] = _param(v)
    return cur, name, params


class Model:
    def __init__(self, spec, work, inject=None, timeout=600):
        self.spec, self.work = spec, Path(work).resolve()
        self.work.mkdir(parents=True, exist_ok=True)
        self.top = spec["top"]
        files = [str(f) for f in spec["files"]]
        incs = list(spec.get("include_dirs") or []) + sorted({str(Path(f).parent) for f in files})
        self.spec = dict(spec, include_dirs=incs)
        self.files = inject_sources(files, work, inject) if inject else files
        self.scope = list(spec.get("scope") or [])
        self.files, self.dropped = usable_files(self.spec, self.files, self.work / "files")
        derived, self.sim_top, self.sim_params = resolve_scope(self.spec, self.files, self.work / "scope")
        self.design_top = self.top
        cut = f"hierarchy -check -top {self.top}\n"
        if self.scope:
            self.top = "x5_scope"
            cut += f"hierarchy -top {derived}\nrename -top x5_scope\n"
        log = ""
        for order in (self.files, top_first(self.files, self.design_top)):
            ys = (
                f"read_verilog -sv {' '.join(_defs(self.spec))} {' '.join(order)}\n" + cut +
                f"prep -flatten -top {self.top}\n"
                "tee -q -o latch.txt select -count t:$dlatch t:$adlatch t:$dlatchsr t:$sr\n"
                "async2sync\ndffunmap\nsetundef -undriven -anyseq\nsetundef -anyseq\nopt_clean\n"
                "tee -q -o clk.txt select -list t:$dff %x:+[CLK] t:$dff %d\n"
                "tee -q -o neg.txt select -count t:$dff r:CLK_POLARITY=0 %i\n"
                "tee -q -o nff.txt select -count t:$dff\n"
                "tee -q -o other.txt select -count t:$ff t:$dffe t:$adff t:$sdff t:$dffsr t:$aldff\n"
                "write_smt2 -wires model.smt2\n"
            )
            (self.work / "model.ys").write_text(ys)
            rc, log = sh([YOSYS, "-q", "-s", "model.ys"], cwd=self.work, timeout=timeout)
            (self.work / "model.log").write_text(log)
            if rc == 0:
                break
        else:
            raise Refuse("yosys cannot build the model: " + (log.strip().splitlines() or ["?"])[-1][:200])
        # The order of the source files is part of the design: a macro defined in one file changes the
        # files read after it. The simulator must read them in the order the model was built from.
        self.source_order = "as listed" if order == self.files else "top module's file first"
        self.files = list(order)
        cnt = lambda n: int(re.findall(r"(\d+) objects", (self.work / n).read_text())[-1])  # noqa: E731
        if cnt("latch.txt"):
            raise Refuse("latches in the design")
        if cnt("other.txt"):
            raise Refuse("flip-flop types left after dffunmap")
        self.nff, neg = cnt("nff.txt"), cnt("neg.txt")
        if self.nff == 0:
            raise Refuse("no flip-flops")
        if neg not in (0, self.nff):
            raise Refuse("flip-flops on both clock edges")
        self.negedge = neg > 0
        clks = sorted({ln.split("/", 1)[1].strip() for ln in (self.work / "clk.txt").read_text().splitlines() if "/" in ln})
        if len(clks) != 1:
            raise Refuse(f"{len(clks)} clock nets: {clks[:4]}")
        self.clock = clks[0]
        self.text = (self.work / "model.smt2").read_text()
        mods = re.findall(r"^; yosys-smt2-module (\S+)", self.text, re.M)
        if len(mods) != 1:
            raise Refuse(f"model has {len(mods)} modules after flatten (black boxes?)")
        self.name = mods[0]
        g = lambda k: {m[0]: int(m[1]) for m in re.findall(rf"^; yosys-smt2-{k} (\S+) (\d+)", self.text, re.M)}  # noqa: E731
        self.inputs, self.wires, self.regs = g("input"), g("wire"), g("register")
        if self.clock not in self.inputs:
            raise Refuse(f"clock {self.clock} is not a top-level input")
        self.regs = {k: v for k, v in self.regs.items() if not k.startswith("$") and k in self.wires}
        # Small memories without initial contents: their power-up contents are part of a trace.
        self.mems = {}
        for nm, ab, w, js in re.findall(r"^; yosys-smt2-memory (\S+) (\d+) (\d+) \d+ \d+ \w+\n; yosys-smt2-witness (\{.*\})$", self.text, re.M):
            try:
                info = json.loads(js)
            except ValueError:
                continue
            size = int(info.get("size", 0))
            if (not nm.startswith("$") and 0 < size <= 256 and size <= 2 ** int(ab)
                    and info.get("uninitialized") == [{"offset": 0, "width": size * int(w)}]):
                self.mems[nm] = {"abits": int(ab), "width": int(w), "size": size}
        if sum(v["size"] for v in self.mems.values()) > 1024:
            self.mems = {}
        # Other names of a register's net. After flatten the model may know a register by the name of
        # a wire it drives; the simulator can only be told a value under the register's own name.
        body = dict(re.findall(r"^\(define-fun \|" + re.escape(self.name) + r"_n ([^|]+)\| \(\(state \|[^|]+\|\)\) (?:Bool|\(_ BitVec \d+\)) (.+)\)$", self.text, re.M))
        direct = re.compile(r"\(\|[^|]+\| state\)|\(= \(\(_ extract 0 0\) \(\|[^|]+\| state\)\) #b1\)")
        same = {}
        for nm, b in body.items():
            if direct.fullmatch(b):
                same.setdefault(b, []).append(nm)
        self.aliases = {n: [x for x in same.get(body.get(n), []) if x != n and not x.startswith("$")] for n in self.regs}
        self.aliases = {n: v for n, v in self.aliases.items() if v}

    def resets(self):
        r = self.spec.get("reset")
        if r is None:
            return [{"port": n, "active_low": bool(LOW_RE.search(n)), "how": "name"} for n in self.inputs
                    if RESET_RE.search(n) and self.inputs[n] == 1]
        out = []
        for x in (r if isinstance(r, list) else [r]):
            if x and x["port"] not in self.inputs:
                raise Refuse(f"reset {x['port']} is not a top-level input")
            if x:
                out.append(dict(x, how=x.get("how", "given")))
        return out


def _val(m, c):
    v = m.eval(c, model_completion=True)
    return int(z3.is_true(v)) if z3.is_bool(c) else v.as_long()


class Kernel:
    def __init__(self, model, obs, reset_cycles=8, check_ms=60000, extra=()):
        self.m, self.R0, self.ms = model, reset_cycles, check_ms
        self.extra = list(extra)
        for x in self.extra:
            if x not in model.wires:
                raise Refuse(f"signal {x} is not in the model")
        self.obs = []
        for o in obs:
            if o not in model.wires:
                raise Refuse(f"observed signal {o} is not in the model")
            self.obs.append((o, model.wires[o]))
        self.W = sum(w for _, w in self.obs)
        self.rst = model.resets()
        self.R = reset_cycles if self.rst else 0
        self.ins = [n for n in model.inputs if n != model.clock]
        self.queries = {"sat": 0, "unsat": 0, "unknown": 0}

    # ---- unrolling -------------------------------------------------------------------------
    def _acc(self, name, tag):
        return f"(|{self.m.name}_n {name}| |s_{tag}|)"

    def _bv(self, name, w, tag):
        a = self._acc(name, tag)
        return f"(ite {a} #b1 #b0)" if w == 1 else a

    def frame(self, tag, regs=False):
        M, t = self.m.name, []
        t.append(f"(declare-fun |s_{tag}| () |{M}_s|)")
        parts = " ".join(self._bv(n, w, tag) for n, w in self.obs)
        t.append(f"(declare-fun |o_{tag}| () (_ BitVec {self.W}))")
        t.append(f"(assert (= |o_{tag}| {parts if len(self.obs) == 1 else '(concat ' + parts + ')'}))")
        for nm, fn in (("is", "is"), ("init", "i")):
            t.append(f"(declare-fun |{nm}_{tag}| () Bool) (assert (= |{nm}_{tag}| (|{M}_{fn}| |s_{tag}|)))")
        act = [(f"(not {self._acc(r['port'], tag)})" if r["active_low"] else self._acc(r["port"], tag)) for r in self.rst]
        t.append(f"(declare-fun |ra_{tag}| () Bool) (assert (= |ra_{tag}| (and true {' '.join(act)})))")
        t.append(f"(declare-fun |rn_{tag}| () Bool) (assert (= |rn_{tag}| (not (or false {' '.join(act)}))))")
        t.append(f"(assert (|{M}_u| |s_{tag}|)) (assert (|{M}_h| |s_{tag}|))")
        fr = {"tag": tag, "o": z3.BitVec(f"o_{tag}", self.W), "ins": {}, "regs": {}}
        for k in ("is", "init", "ra", "rn"):
            fr[k] = z3.Bool(f"{k}_{tag}")
        for grp, names, widths in (("ins", self.ins, self.m.inputs), ("regs", list(self.m.regs) if regs else [], self.m.regs)):
            for j, n in enumerate(names):
                w = widths[n]
                c = f"{grp[0]}_{tag}_{j}"
                t.append(f"(declare-fun |{c}| () (_ BitVec {w})) (assert (= |{c}| {self._bv(n, w, tag)}))")
                fr[grp][n] = z3.BitVec(c, w)
        fr["x"] = []
        for j, n in enumerate(self.extra):
            c, acc = f"x_{tag}_{j}", self._acc(n, tag)
            if self.m.wires[n] != 1:
                acc = f"(distinct {acc} (_ bv0 {self.m.wires[n]}))"
            t.append(f"(declare-fun |{c}| () Bool) (assert (= |{c}| {acc}))")
            fr["x"].append(z3.Bool(c))
        fr["mems"] = {}
        for j, (n, d) in enumerate(self.m.mems.items() if regs else ()):
            fr["mems"][n] = []
            for a in range(d["size"]):
                c = f"m_{tag}_{j}_{a}"
                t.append(f"(declare-fun |{c}| () (_ BitVec {d['width']})) "
                         f"(assert (= |{c}| (select (|{M}_m {n}| |s_{tag}|) (_ bv{a} {d['abits']}))))")
                fr["mems"][n].append(z3.BitVec(c, d["width"]))
        fr["local"] = list(z3.parse_smt2_string(self.m.text + "\n" + "\n".join(t)))
        return fr

    def _power_up(self, mdl, f0):
        """The power-up state a model chose: named registers and the words of small memories."""
        return {"init_regs": {n: _val(mdl, c) for n, c in f0["regs"].items()},
                "init_mems": {n: [_val(mdl, c) for c in cs] for n, cs in f0["mems"].items()}}

    def trans(self, a, b):
        M = self.m.name
        txt = f"(declare-fun |s_{a['tag']}| () |{M}_s|) (declare-fun |s_{b['tag']}| () |{M}_s|) (assert (|{M}_t| |s_{a['tag']}| |s_{b['tag']}|))"
        return list(z3.parse_smt2_string(self.m.text + "\n" + txt))

    def solver(self):
        s = z3.SolverFor("QF_AUFBV")
        s.set("timeout", self.ms)
        return s

    def check(self, s):
        r = s.check()
        self.queries[str(r)] += 1
        return r

    @staticmethod
    def member(x, y, E):
        by = {}
        for a, b in E:
            by.setdefault(a, []).append(b)
        return z3.Or([z3.And(x == a, z3.Or([y == b for b in bs])) for a, bs in by.items()]) if by else z3.BoolVal(False)

    # ---- W: witnesses ----------------------------------------------------------------------
    def witness_init(self):
        self.ws, self.wf = self.solver(), []
        self.E, self.traces, self.depth = {}, [], self.R
        self._w_frame()
        for _ in range(self.R):
            self._w_frame()
        if self.check(self.ws) != z3.sat:
            raise Refuse("the initial condition is unsatisfiable or too hard")

    def _w_frame(self):
        t = len(self.wf)
        f = self.frame(f"w{t}", regs=(t == 0))
        self.ws.add(f["local"])
        if t == 0:
            self.ws.add(f["init"], f["is"])
        else:
            self.ws.add(z3.Not(f["is"]))
            self.ws.add(self.trans(self.wf[-1], f))
        if self.rst:
            self.ws.add(f["ra"] if t < self.R else f["rn"])
        self.wf.append(f)

    def witness_step(self, max_states):
        """One more depth. -> 'ok' | 'unknown'. Afterwards every pair at steps < self.depth is in E."""
        d = self.depth
        while len(self.wf) <= d + 1:
            self._w_frame()
        s, f = self.ws, self.wf
        s.push()
        for a, b in self.E:
            s.add(z3.Or(f[d]["o"] != a, f[d + 1]["o"] != b))
        while True:
            r = self.check(s)
            if r == z3.unsat:
                break
            if r != z3.sat:
                s.pop()
                return "unknown"
            mdl = s.model()
            seq = [_val(mdl, f[t]["o"]) for t in range(d + 2)]
            tr = {"obs": seq, "inputs": {n: [_val(mdl, f[t]["ins"][n]) for t in range(d + 2)] for n in self.ins},
                  "origin": "bmc", **self._power_up(mdl, f[0])}
            tid, new = len(self.traces), 0
            for t in range(self.R, d + 1):
                p = (seq[t], seq[t + 1])
                if p not in self.E:
                    self.E[p] = (tid, t)
                    s.add(z3.Or(f[d]["o"] != p[0], f[d + 1]["o"] != p[1]))
                    new += 1
            assert new, "model without a new pair"
            self.traces.append(tr)
            if len(self.states()) > max_states:
                s.pop()
                raise Refuse(f"more than {max_states} observed states; propose predicates instead of raw values")
        s.pop()
        self.depth = d + 1
        return "ok"

    def states(self):
        return {x for p in self.E for x in p}

    # ---- entry states and the local closure (upper bound) ------------------------------------
    def entry_states(self, cap):
        """Every observation possible in the first cycle after reset. None: more than `cap`."""
        s, f, out = self.ws, self.wf, []
        s.push()
        while True:
            r = self.check(s)
            if r == z3.unsat:
                break
            if r != z3.sat or len(out) >= cap:
                s.pop()
                return None
            v = _val(s.model(), f[self.R]["o"])
            out.append(v)
            s.add(f[self.R]["o"] != v)
        s.pop()
        return out

    def closure(self, entry, max_states):
        """Successors from an ARBITRARY state with a given observation, closed from the entry states.
        Every real transition is in the result (the real state is one of the arbitrary ones), so the
        result is complete without any depth bound. None: too many states, or the solver gave up."""
        s, a, b = self.solver(), self.frame("la"), self.frame("lb")
        for fr in (a, b):
            s.add(fr["local"])
            s.add(z3.Not(fr["is"]))
            if self.rst:
                s.add(fr["rn"])
        s.add(self.trans(a, b))
        S, E, todo = set(entry), set(), list(entry)
        while todo:
            x = todo.pop()
            s.push()
            s.add(a["o"] == x)
            while True:
                r = self.check(s)
                if r == z3.unsat:
                    break
                if r != z3.sat:
                    return None
                v = _val(s.model(), b["o"])
                E.add((x, v))
                s.add(b["o"] != v)
                if v not in S:
                    S.add(v)
                    todo.append(v)
                if len(S) > max_states:
                    return None
            s.pop()
        return S, E

    # ---- witness search continued from a concrete trace -----------------------------------------
    def extend(self, tid, targets, D):
        """Pin the inputs of trace `tid` and look D cycles further for a pair in `targets`.
        -> 'found' (a longer trace was added) | 'exhausted' | 'unknown'."""
        tr = self.traces[tid]
        n = len(tr["obs"]) - 1
        while len(self.wf) <= n + D:
            self._w_frame()
        s, f = self.ws, self.wf
        s.push()
        for t in range(n):
            for name, vals in tr["inputs"].items():
                s.add(f[t]["ins"][name] == vals[t])
        for name, v in tr["init_regs"].items():
            s.add(f[0]["regs"][name] == v)
        for name, vals in (tr.get("init_mems") or {}).items():
            for c, v in zip(f[0]["mems"][name], vals):
                s.add(c == v)
        by = {}
        for a, b in targets:
            by.setdefault(a, []).append(b)
        s.add(z3.Or([z3.And(f[t]["o"] == a, z3.Or([f[t + 1]["o"] == b for b in bs]))
                     for t in range(max(n, self.R), n + D) for a, bs in by.items()]))
        r = self.check(s)
        if r != z3.sat:
            s.pop()
            return "exhausted" if r == z3.unsat else "unknown"
        mdl = s.model()
        seq = [_val(mdl, f[t]["o"]) for t in range(n + D + 1)]
        end = next(t for t in range(max(n, self.R), n + D) if (seq[t], seq[t + 1]) in targets) + 1
        new = {"obs": seq[:end + 1], "inputs": {x: [_val(mdl, f[t]["ins"][x]) for t in range(end + 1)] for x in self.ins},
               "origin": "bmc continued from a trace", "from": tid, **self._power_up(mdl, f[0])}
        s.pop()
        nid = len(self.traces)
        for t in range(self.R, end):
            self.E.setdefault((seq[t], seq[t + 1]), (nid, t))
        self.traces.append(new)
        return "found"

    # ---- witness search continued from a state the simulator reached ---------------------------
    def relay_init(self, D, ms=20000):
        self.rs, self.rf = self.solver(), []
        self.rs.set("timeout", ms)
        for t in range(D + 1):
            fr = self.frame(f"r{t}", regs=(t == 0))
            self.rs.add(fr["local"])
            self.rs.add(z3.Not(fr["is"]))
            if self.rst:
                self.rs.add(fr["rn"])
            if self.rf:
                self.rs.add(self.trans(self.rf[-1], fr))
            self.rf.append(fr)

    def relay(self, snap, targets, D):
        """From the register and memory values the simulator had at some cycle, look D cycles ahead
        for a pair in `targets`. What the snapshot does not cover (unnamed registers, unknown values)
        is left free, so the answer is only a proposal: the caller replays it from reset.
        -> {obs, inputs} of the continuation, frame 0 being the snapshot cycle, or None."""
        s, f = self.rs, self.rf
        s.push()
        for n, v in snap["regs"].items():
            if n in f[0]["regs"]:
                s.add(f[0]["regs"][n] == v)
        for n, words in snap["mems"].items():
            for a, v in words.items():
                if n in f[0]["mems"] and a < len(f[0]["mems"][n]):
                    s.add(f[0]["mems"][n][a] == v)
        by = {}
        for a, b in targets:
            by.setdefault(a, []).append(b)
        s.add(z3.Or([z3.And(f[t]["o"] == a, z3.Or([f[t + 1]["o"] == b for b in bs])) for t in range(D) for a, bs in by.items()]))
        if self.check(s) != z3.sat:
            s.pop()
            return None
        mdl = s.model()
        seq = [_val(mdl, f[t]["o"]) for t in range(D + 1)]
        end = next(t for t in range(D) if (seq[t], seq[t + 1]) in targets) + 1
        out = {"obs": seq[:end + 1], "inputs": {x: [_val(mdl, f[t]["ins"][x]) for t in range(end + 1)] for x in self.ins}}
        s.pop()
        return out

    # ---- I: induction ----------------------------------------------------------------------
    def induct(self, E, k, grow=0):
        """-> (status, U). status: proven | open | unknown. U: undetermined pairs added to close it."""
        s, f = self.solver(), []
        for t in range(k + 2):
            fr = self.frame(f"i{k}_{t}")
            s.add(fr["local"])
            s.add(z3.Not(fr["is"]))
            if self.rst:
                s.add(fr["rn"])
            if f:
                s.add(self.trans(f[-1], fr))
            f.append(fr)
        U = set()
        while True:
            Ea = set(E) | U
            s.push()
            for t in range(k):
                s.add(self.member(f[t]["o"], f[t + 1]["o"], Ea))
            if k == 0:
                s.add(z3.Or([f[0]["o"] == a for a in {x for p in Ea for x in p}]))
            s.add(z3.Not(self.member(f[k]["o"], f[k + 1]["o"], Ea)))
            r = self.check(s)
            if r == z3.unsat:
                return "proven", U
            if r != z3.sat:
                return "unknown", U
            mdl = s.model()
            p = (_val(mdl, f[k]["o"]), _val(mdl, f[k + 1]["o"]))
            s.pop()
            if len(U) >= grow:
                return "open", U | {p}
            U.add(p)


# ---- R: replay in Icarus Verilog --------------------------------------------------------------
def _ident(n):
    return n if re.fullmatch(r"[A-Za-z_][\w$]*(\[\d+\])?(\.[A-Za-z_][\w$]*(\[\d+\])?)*", n) else None


# One compilation unit for all files, no -u: a macro defined in one file is seen by the files read
# after it, as in Yosys's read_verilog. With -u each file starts with no macros, and a design whose
# top file configures its submodules by `define (picosoc does) becomes another design. The
# testbench comes first so that no macro of the design can change the testbench.
IVERILOG = ["iverilog", "-g2012", "-s", "x5_tb"]


def sim_files(m, work):
    """Sources for the simulator, in the configuration Yosys synthesizes: the same file order
    (m.files), SYNTHESIS and YOSYS defined as Yosys defines them, and the simulator's own predefined
    macro neutralized, so `ifdef __ICARUS__ branches are not taken. Otherwise the simulator would
    run a different design than the one the proof is about."""
    out, changed = [], False
    d = Path(work) / "simsrc"
    for i, f in enumerate(m.files):
        text = Path(f).read_text(errors="replace")
        if "__ICARUS__" in text:
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{i}_{Path(f).name}"
            p.write_text(text.replace("__ICARUS__", "x5_not_icarus"))
            out.append(str(p))
            changed = True
        else:
            out.append(f)
    extra = ["-DSYNTHESIS", "-DYOSYS"]
    for idir in m.spec.get("include_dirs") or []:  # headers that switch on the simulator macro, too
        inc = d / Path(idir).name
        for h in sorted(Path(idir).glob("*")):
            if h.is_file() and h.suffix in (".vh", ".svh", ".h", ".v", ".sv", ".inc") and h.stat().st_size < 2_000_000:
                text = h.read_text(errors="replace")
                if "__ICARUS__" in text:
                    inc.mkdir(parents=True, exist_ok=True)
                    (inc / h.name).write_text(text.replace("__ICARUS__", "x5_not_icarus"))
                    changed = True
        if inc.exists() and "-I" + str(inc) not in extra:
            extra.append("-I" + str(inc))
    return out, extra, changed


def _tb_head(kern):
    """Declarations shared by the replay and the random-simulation testbench: clock, one input
    vector `cur` sliced onto the ports, the instance, the observation as one concatenation."""
    m = kern.m
    idle, act = ("1", "0") if m.negedge else ("0", "1")
    obs = [_ident(n) for n, _ in kern.obs]
    if None in obs:
        return None
    win = sum(m.inputs[n] for n in kern.ins)
    L = ["`timescale 1ns/1ps", "module x5_tb;", f"  reg x5_clk = {idle};", f"  reg [{max(win, 1) - 1}:0] cur;"]
    conn, lo = [], win
    for n in kern.ins:
        lo -= m.inputs[n]
        conn.append(f", .{n}(cur[{lo + m.inputs[n] - 1}:{lo}])")
    par = (" #(" + ", ".join(f".{k}({v})" for k, v in m.sim_params.items()) + ")") if m.sim_params else ""
    L.append(f"  {m.sim_top}{par} dut (.{m.clock}(x5_clk)" + "".join(conn) + ");")
    return L, "{" + ", ".join("dut." + n for n in obs) + "}", win, idle, act


def _pack(kern, tr, t):
    v = 0
    for n in kern.ins:
        v = (v << kern.m.inputs[n]) | tr["inputs"][n][t]
    return v


def replay(kern, traces, work, deposit=True, timeout=900):
    """-> per trace: number of leading frames (from the first frame after reset) the simulator agrees on."""
    m, work = kern.m, Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    head = _tb_head(kern)
    if head is None:
        return None, "observed signal has no hierarchical name"
    L, cat, win, idle, act = head
    digits = (max(win, 1) + 3) // 4
    for tid, tr in enumerate(traces):
        (work / f"tr{tid}.hex").write_text("".join(f"{_pack(kern, tr, t):0{digits}x}\n" for t in range(len(tr["obs"]))))
    nmax = max(len(tr["obs"]) for tr in traces)
    L += [f"  reg [{max(win, 1) - 1}:0] vec [0:{nmax - 1}];", "  integer x5_t, x5_n, x5_i;", "  reg x5_bad = 0;", "  initial begin",
          '    if (!$value$plusargs("t=%d", x5_t)) x5_t = 0;', "    x5_n = 0;", "    #1;  // the RTL's own initial values are in place",
          "    case (x5_t)"]
    soft = []
    for tid, tr in enumerate(traces):
        L.append(f'    {tid}: begin x5_n = {len(tr["obs"])}; $readmemh("tr{tid}.hex", vec);')
        for ln in (_deposits(m, tr) if deposit else []):
            soft.append(len(L))
            L.append(ln)
        L.append("    end")
    L += ["    endcase", '    if (x5_bad) $display("X5BAD;");', "    for (x5_i = 0; x5_i < x5_n; x5_i = x5_i + 1) begin", "      cur = vec[x5_i];",
          f'      #4 $display("X5O%0d:%b;", x5_i, {cat}); #1 x5_clk = {act}; #5 x5_clk = {idle};', "    end", "    $finish;", "  end", "endmodule"]
    ok, dropped, log = _compile(m, work, work / "x5_tb.sv", L, soft, "tb.vvp", timeout)
    (work / "iverilog.log").write_text(log)
    if not ok:
        return None, "iverilog: " + (log.strip().splitlines() or ["?"])[-1][:200]
    out = []
    for tid, tr in enumerate(traces):
        rc, log = sh(["vvp", "-n", "tb.vvp", f"+t={tid}"], cwd=work, timeout=timeout)
        got = dict(re.findall(r"X5O(\d+):([01xzXZ]+);", log))
        n = 0
        for t in range(kern.R, len(tr["obs"]) if "X5BAD;" not in log else 0):
            if tr["obs"][t] is None or got.get(str(t)) != format(tr["obs"][t], f"0{kern.W}b"):
                break
            n += 1
        out.append(n)
    how = "deposit" if soft else "no-deposit"
    if dropped:
        how += f", {len(dropped)} of {len(soft)} values not accepted by the simulator"
    return out, how


def _compile(m, work, tb, L, soft, out, timeout):
    """iverilog on the testbench lines L. A line whose index is in `soft` (a deposit, a probe) is
    blanked when the compiler rejects it, so a name the simulator does not know costs only itself.
    -> (compiled, indices of the lines dropped, compiler log)"""
    files, extra, _ = sim_files(m, work)
    dropped, log = set(), ""
    for _ in range(120):  # the simulator may stop at the first line it cannot take, so one round per line
        tb.write_text(chr(10).join(L))
        rc, log = sh(IVERILOG + ["-o", out] + extra + _defs(m.spec) + [str(tb)] + files, cwd=work, timeout=timeout)
        if rc == 0:
            return True, dropped, log
        bad = ({int(x) - 1 for x in re.findall(re.escape(tb.name) + r":(\d+):", log)} & set(soft)) - dropped
        if not bad:
            break
        for i in bad:
            L[i] = ""
        dropped |= bad
    return False, dropped, log


def _deposits(m, tr):
    """Testbench lines that put a trace's power-up state into the simulator. A value is written only
    where the RTL left the bits unknown. A register or memory word the RTL initializes keeps its
    value, and a trace that asks for another one is reported (x5_bad): it is not an execution of
    this design."""
    out = []
    put = lambda lhs, w, v: f"      if ((|({lhs} ^ {w}'h{v:x})) === 1'b1) x5_bad = 1; else {lhs} = {w}'h{v:x};"  # noqa: E731
    al = getattr(m, "aliases", {})
    for n, v in (tr.get("init_regs") or {}).items():
        if n in m.regs:
            out += [put("dut." + a, m.regs[n], v) for a in [n] + al.get(n, []) if _ident(a)]
    mems = getattr(m, "mems", {})
    for n, vals in (tr.get("init_mems") or {}).items():
        if n in mems and _ident(n):
            out += [put(f"dut.{n}[{a}]", mems[n]["width"], v) for a, v in enumerate(vals)]
    return out


class Driver:
    """One compiled testbench that applies any recorded input sequence from reset. It prints the
    observation every cycle and, at the cycles asked for, every named register and small memory."""

    def __init__(self, kern, work, cap, timeout=900):
        m = kern.m
        self.k, self.work, self.cap, self.timeout, self.ok = kern, Path(work).resolve(), cap, timeout, False
        self.work.mkdir(parents=True, exist_ok=True)
        head = _tb_head(kern)
        if head is None:
            return
        L, cat, win, idle, act = head
        self.digits = (max(win, 1) + 3) // 4
        self.regs = [n for n in m.regs if _ident(n)]
        self.mems = [n for n in m.mems if _ident(n)]
        L += [f"  reg [{max(win, 1) - 1}:0] vec [0:{cap - 1}];", "  reg [31:0] x5_sn [0:255];", "  integer x5_n, x5_i, x5_p, x5_j;", "  initial begin",
              '    if (!$value$plusargs("n=%d", x5_n)) x5_n = 0;', '    $readmemh("in.hex", vec); $readmemh("sn.hex", x5_sn);', "    x5_p = 0;", "    #1;",
              "    for (x5_i = 0; x5_i < x5_n; x5_i = x5_i + 1) begin", "      cur = vec[x5_i];", f'      #4 $display("X5O%0d:%b;", x5_i, {cat});',
              "      if (x5_i == x5_sn[x5_p]) begin", "        x5_p = x5_p + 1;", '        $write("X5R%0d:", x5_i);']
        soft = []
        for j, n in enumerate(self.regs):
            soft.append(len(L))
            L.append(f'        $write("%0d=%h,", {j}, dut.{n});')
        L.append('        $write(";\\n");')
        for j, n in enumerate(self.mems):
            soft.append(len(L))
            L.append(f'        for (x5_j = 0; x5_j < {m.mems[n]["size"]}; x5_j = x5_j + 1) $write("X5M%0d:%0d:%0d=%h;\\n", x5_i, {j}, x5_j, dut.{n}[x5_j]);')
        L += ["      end", f"      #1 x5_clk = {act}; #5 x5_clk = {idle};", "    end", "    $finish;", "  end", "endmodule"]
        self.ok, self.dropped, log = _compile(m, self.work, self.work / "x5_drv.sv", L, soft, "drv.vvp", timeout)
        (self.work / "iverilog.log").write_text(log)

    def run(self, inputs, n, snaps=()):
        """Apply `inputs` for n cycles from reset. -> (observation per cycle as a bit string,
        {cycle: {"regs": {name: value}, "mems": {name: {address: value}}}}); unknown values are left out."""
        k = self.k
        tr = {"inputs": inputs}
        (self.work / "in.hex").write_text("".join(f"{_pack(k, tr, t):0{self.digits}x}\n" for t in range(n)))
        (self.work / "sn.hex").write_text("".join(f"{c:x}\n" for c in sorted(snaps)[:255]) + "ffffffff\n")
        rc, log = sh(["vvp", "-n", "drv.vvp", f"+n={n}"], cwd=self.work, timeout=self.timeout)
        obs = dict(re.findall(r"X5O(\d+):([01xzXZ]+);", log))
        known = lambda h: not set(h.lower()) & {"x", "z"}  # noqa: E731
        dumps = {}
        for c, body in re.findall(r"X5R(\d+):([^;]*);", log):
            dumps[int(c)] = {"regs": {self.regs[int(j)]: int(h, 16) for j, h in re.findall(r"(\d+)=([0-9a-fA-FxzXZ]+),", body) if known(h)}, "mems": {}}
        for c, j, a, h in re.findall(r"X5M(\d+):(\d+):(\d+)=([0-9a-fA-FxzXZ]+);", log):
            if int(c) in dumps and known(h):
                dumps[int(c)]["mems"].setdefault(self.mems[int(j)], {})[int(a)] = int(h, 16)
        return [obs.get(str(t)) for t in range(n)], dumps


def relay_phase(k, pool, Ec, work, left, per_state=6, Ds=(1, 4, 12), max_prefix=4000, rounds=8, retries=3, seed=1):
    """Snapshot relay: witnesses for closure edges the other searches missed.
    `pool` holds executions from reset that the simulator produced (inputs and observations). The
    simulator is run again over a prefix of one and dumps its registers at a chosen cycle; the solver
    starts from exactly that state and looks a few cycles ahead for an edge still without a witness;
    the prefix and the solver's continuation are then replayed from reset, inputs only. Only a
    continuation the simulator reproduces is kept, so nothing here is trusted: not the snapshot, not
    the model's free values, not the solver. The end of every new trace becomes a snapshot point of
    the next round, which is how states no simulation reached get explored."""
    import random
    stats = {"snapshots": 0, "found": 0, "pairs": 0, "rejected": 0, "rounds": 0}
    if not pool or not (Ec - set(k.E)):
        return stats
    drv = Driver(k, work, max_prefix + (rounds + 1) * max(Ds) + 8)
    if not drv.ok:
        return dict(stats, error="simulator testbench did not compile")
    k.relay_init(max(Ds))
    succ = {}
    for a, b in Ec:
        succ.setdefault(a, set()).add(b)

    def near(v, D):  # can an edge without a witness start within D - 1 steps of v?
        src = {a for a, _ in Ec - set(k.E)}
        seen = cur = {v}
        for _ in range(D):
            if cur & src:
                return True
            cur = {y for x in cur for y in succ.get(x, ())} - seen
            seen = seen | cur
        return False

    rng, pts, mid = random.Random(seed), {}, {}
    for i, tr in enumerate(pool):
        o = tr["obs"]
        lim = min(next((t for t in range(k.R, len(o)) if o[t] is None), len(o)), max_prefix)
        for t in range(k.R + 1, lim):
            if t == k.R + 1 or o[t] != o[t - 1] or (t + 1 < lim and o[t + 1] != o[t]):
                pts.setdefault(o[t], []).append((i, t))  # the first and the last cycle of a visit to a state
            else:
                mid.setdefault(o[t], []).append((i, t))  # inside a visit: the same state, other register values
    queue = []
    for v in sorted(set(pts) | set(mid)):
        a, b = pts.get(v, []), mid.get(v, [])
        pick = [min(a + b, key=lambda x: x[1])] + rng.sample(a, min(len(a), per_state // 2)) + rng.sample(b, min(len(b), per_state // 2))
        queue += [(i, t, v) for i, t in dict.fromkeys(pick)]
    fmt = lambda v: format(v, f"0{k.W}b")  # noqa: E731
    for _ in range(rounds):
        if not queue or left() <= 0 or not (Ec - set(k.E)):
            break
        stats["rounds"] += 1
        byrun, snaps = {}, {}
        for i, t, v in queue:
            byrun.setdefault(i, []).append(t)
        for i, ts in byrun.items():
            if left() <= 0:
                break
            ts = sorted(set(ts))[:255]
            obs, dumps = drv.run(pool[i]["inputs"], max(ts) + 1, ts)
            for t in ts:
                if t in dumps and obs[t] == fmt(pool[i]["obs"][t]):
                    snaps[(i, t)] = dumps[t]
        stats["snapshots"] += len(snaps)
        batch, queue, bad = [q for q in queue if (q[0], q[1]) in snaps], [], {}
        for D in Ds:
            for i, t, v in batch:
                while left() > 0 and len(bad.get((i, t), ())) < retries:
                    targets = Ec - set(k.E) - bad.get((i, t), set())
                    if not targets or not near(v, D):
                        break
                    tail = k.relay(snaps[(i, t)], targets, D)
                    if tail is None:
                        break
                    base = pool[i]
                    tr = {"obs": base["obs"][:t] + tail["obs"], "inputs": {x: base["inputs"][x][:t] + tail["inputs"][x] for x in k.ins},
                          "init_regs": {}, "init_mems": {}, "origin": "snapshot relay"}
                    n = len(tr["obs"])
                    got, _ = drv.run(tr["inputs"], n)
                    if any(tr["obs"][u] is None or got[u] != fmt(tr["obs"][u]) for u in range(k.R, n)):
                        stats["rejected"] += 1  # the continuation relied on something the snapshot did not pin
                        bad.setdefault((i, t), set()).add((tr["obs"][-2], tr["obs"][-1]))
                        continue
                    tid, new = len(k.traces), 0
                    for u in range(max(t, k.R), n - 1):
                        p = (tr["obs"][u], tr["obs"][u + 1])
                        if p not in k.E:
                            k.E[p] = (tid, u)
                            new += 1
                    k.traces.append(tr)
                    pool.append(tr)
                    queue.append((len(pool) - 1, n - 1, tr["obs"][-1]))
                    stats["found"] += 1
                    stats["pairs"] += new
    return stats


def simulate(kern, work, runs=12, cycles=3000, seed=1, timeout=900, stim=None):
    """Random simulation in Icarus Verilog. Every observed pair is a real transition by construction.
    Each input is driven in one of eight ways per run (0 uniform, 1 mostly ones, 2 mostly zeros,
    3 held about 8 cycles, 4 zero with a rare random pulse, 5 all ones with a rare random pulse,
    6 held about 64 cycles, 7 held about 512 cycles); reset follows the protocol. -> list of {obs, inputs, init_regs} with unknown observations
    as None. Stimulus quality only affects how many edges get a witness, never whether one is true."""
    import random
    m, work = kern.m, Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    head = _tb_head(kern)
    if head is None:
        return []
    L, cat, win, idle, act = head
    ni = len(kern.ins)
    rports = {r["port"]: r for r in kern.rst}
    L += ["  integer x5_n, x5_i, x5_s;", f"  reg [{max(3 * ni, 1) - 1}:0] x5_m;", "  reg [31:0] x5_a, x5_b;", "  initial begin",
          '    if (!$value$plusargs("s=%d", x5_s)) x5_s = 1;', '    if (!$value$plusargs("n=%d", x5_n)) x5_n = 100;',
          '    if (!$value$plusargs("m=%h", x5_m)) x5_m = 0;', "    cur = 0;", "    for (x5_i = 0; x5_i < x5_n; x5_i = x5_i + 1) begin"]
    lo = win
    for jn, n in enumerate(kern.ins):
        w = m.inputs[n]
        lo -= w
        sl = f"cur[{lo + w - 1}:{lo}]"
        if n in rports:
            a = "0" if rports[n]["active_low"] else "1"
            L.append(f"      {sl} = (x5_i < {kern.R}) ? 1'b{a} : 1'b{1 - int(a)};")
            continue
        if stim and isinstance(stim.get(n), dict):
            L.append(f"      {sl} = {w}'d{int(stim[n]['value'])};")
            continue
        k32 = (w + 31) // 32
        rnd = lambda: "{" + ", ".join("$random(x5_s)" for _ in range(k32)) + "}"  # noqa: E731
        L.append(f"      case (x5_m[{3 * jn + 2}:{3 * jn}])")
        L.append(f"        0: {sl} = {rnd()};")
        L.append(f"        1: {sl} = {rnd()} | {rnd()};")
        L.append(f"        2: {sl} = {rnd()} & {rnd()};")
        L.append(f"        3: begin x5_a = $random(x5_s); if (x5_a[2:0] == 0) {sl} = {rnd()}; end")
        L.append(f"        4: begin x5_a = $random(x5_s); {sl} = (x5_a[5:0] == 0) ? {rnd()} : 0; end")
        L.append(f"        5: begin x5_a = $random(x5_s); {sl} = (x5_a[5:0] == 0) ? {rnd()} : ~0; end")
        L.append(f"        6: begin x5_a = $random(x5_s); if (x5_a[5:0] == 0) {sl} = {rnd()}; end")
        L.append(f"        7: begin x5_a = $random(x5_s); if (x5_a[8:0] == 0 || x5_i <= {kern.R}) {sl} = {rnd()}; end")
        L.append("      endcase")
    L += [f'      #4 $display("X5S%b:%h;", {cat}, cur); #1 x5_clk = {act}; #5 x5_clk = {idle};', "    end", "    $finish;", "  end", "endmodule"]
    tb = work / "x5_sim.sv"
    tb.write_text(chr(10).join(L))
    files, extra, _ = sim_files(m, work)
    rc, log = sh(IVERILOG + ["-o", "sim.vvp"] + extra + _defs(m.spec) + [str(tb)] + files, cwd=work, timeout=timeout)
    (work / "iverilog.log").write_text(log)
    if rc != 0:
        return []
    rng, out = random.Random(seed), []
    for r in range(runs):
        mv = 0 if r == 0 and not stim else rng.getrandbits(max(3 * ni, 1))
        for jn, n in enumerate(kern.ins):  # a proposed driving style for an input (0..7) is used in every run
            if stim and n in stim and not isinstance(stim[n], dict):
                mv = (mv & ~(7 << (3 * jn))) | (int(stim[n]) << (3 * jn))
        rc, log = sh(["vvp", "-n", "sim.vvp", f"+s={seed * 1000 + r}", f"+n={cycles}", f"+m={mv:x}"], cwd=work, timeout=timeout)
        obs, ins = [], {n: [] for n in kern.ins}
        for o, c in re.findall(r"X5S([01xzXZ]+):([0-9a-fA-FxzXZ]+);", log):
            obs.append(int(o, 2) if set(o) <= {"0", "1"} else None)
            cv = int(c, 16) if not set(c.lower()) & {"x", "z"} else 0
            sh_ = win
            for n in kern.ins:
                sh_ -= m.inputs[n]
                ins[n].append((cv >> sh_) & ((1 << m.inputs[n]) - 1))
        out.append({"obs": obs, "inputs": ins, "init_regs": {}})
    return out


# ---- driver -----------------------------------------------------------------------------------
def same_design(k, work):
    """Structural cross-check of the two front ends: every named register and memory of the Yosys
    model must exist in the simulator under the same hierarchical name. A name the simulator does
    not know means it elaborated another configuration (another `define, another generate branch)
    or names things differently; either way the replay is not evidence about the model until a
    person has looked. -> {"registers": n, "memories": n, "unknown_to_simulator": [names]}"""
    m = k.m
    head = _tb_head(k)
    if head is None:
        return {"error": "observed signal has no hierarchical name"}
    L = head[0] + ["  initial begin", "    #1;"]
    names = [n for n in m.regs if _ident(n)] + [n + "[0]" for n in getattr(m, "mems", {}) if _ident(n)]
    soft = {}
    for n in names:
        soft[len(L)] = n
        L.append(f'    $display("X5P %0d", $bits(dut.{n}));')
    L += ["    $finish;", "  end", "endmodule"]
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    ok, dropped, log = _compile(m, work, work / "x5_probe.sv", L, list(soft), "probe.vvp", 300)
    (work / "iverilog.log").write_text(log)
    if not ok:
        return {"error": "probe testbench did not compile: " + (log.strip().splitlines() or ["?"])[-1][:200]}
    unknown = sorted(soft[i] for i in dropped)
    return {"registers": sum(1 for n in m.regs if _ident(n)), "memories": len(getattr(m, "mems", {})),
            "not_identifiers": sorted(n for n in m.regs if not _ident(n)), "unknown_to_simulator": unknown}


def confirm(k, work, do_replay=True):
    """Replay every trace that carries an edge, first from reset with inputs only, then (where that
    is not enough) with the trace's power-up state put into the simulator.
    -> (traces, {trace id: index}, {pair: True | False | None}, indices of the traces that need
    their power-up state, replay mode, agreeing frames per trace)"""
    used = sorted({tid for tid, _ in k.E.values()})
    remap = {tid: i for i, tid in enumerate(used)}
    traces = [k.traces[tid] for tid in used]
    if not (do_replay and traces):
        return traces, remap, {p: None for p in k.E}, set(), "not run", None
    has = lambda tr: bool(tr.get("init_regs") or tr.get("init_mems"))  # noqa: E731
    r0, how = replay(k, traces, work / "replay0", deposit=False)
    r1 = None
    if r0 is None or any(has(tr) and r0[i] < len(tr["obs"]) - k.R for i, tr in enumerate(traces)):
        r1, how1 = replay(k, traces, work / "replay", deposit=True)
        how = how1 if r1 is not None else how
    if r0 is None and r1 is None:
        return traces, remap, {p: None for p in k.E}, set(), how, None
    ok, keep = {}, set()
    for p, (tid, t) in k.E.items():
        i, need = remap[tid], (t - k.R) + 2
        ok[p] = (r0 is not None and r0[i] >= need, r1 is not None and has(traces[i]) and r1[i] >= need)
        if ok[p][1] and not ok[p][0]:
            keep.add(i)
    # a trace that keeps its power-up state is judged with it for all of its edges: that is how the
    # certificate's reader will replay it
    verdict = {p: ok[p][1 if remap[tid] in keep else 0] for p, (tid, _) in k.E.items()}
    counts = [(r1 if i in keep else r0 if r0 is not None else r1)[i] for i in range(len(traces))]
    return traces, remap, verdict, keep, how, counts


def project(cert, n_keep):
    """Keep the first n_keep observed signals of a certificate and drop the others.
    A transition of the kept signals happens only if some transition of the full observation does,
    so the projected edge set is complete whenever the full one is, and an edge is witnessed as soon
    as one of the edges it stands for is. The full edge set stays in the certificate as
    `completeness.support`: the checker proves that set and recomputes the projection itself."""
    ob = cert["observation"]
    sh_ = sum(o["width"] for o in ob[n_keep:])
    rank = lambda e: (e["status"] != "witnessed", bool(e.get("needs_power_up")), e["status"] != "model-witness")  # noqa: E731
    best = {}
    for e in cert["edges"]:
        p = (e["src"] >> sh_, e["dst"] >> sh_)
        if p not in best or rank(e) < rank(best[p]):
            best[p] = e
    edges = [dict(e, src=p[0], dst=p[1]) for p, e in sorted(best.items())]
    st = {}
    for s in cert["states"]:
        o = st.setdefault(s["value"] >> sh_, {"value": s["value"] >> sh_, "status": "undetermined", "entry": False})
        o["status"] = "witnessed" if s["status"] == "witnessed" else o["status"]
        o["entry"] = o["entry"] or s["entry"]
    comp = dict(cert["completeness"], undetermined=sum(e["status"] == "undetermined" for e in edges))
    comp["support"] = {"observation": ob, "width": cert["width"], "states": len(cert["states"]),
                       "pairs": sorted([e["src"], e["dst"]] for e in cert["edges"])}
    return dict(cert, observation=ob[:n_keep], width=cert["width"] - sh_, edges=edges, states=[st[v] for v in sorted(st)], completeness=comp,
                traces=[dict(t, obs=[None if v is None else v >> sh_ for v in t["obs"]]) for t in cert["traces"]])  # None: unknown before reset


def prove(spec, obs, work, depth=40, shallow=12, max_states=64, budget=300, ks=(1, 2, 4), grow=24, reset_cycles=8,
          check_ms=60000, windows=(16, 48, 128), max_len=700, inject=None, do_replay=True, sim_runs=32, sim_cycles=4000, stim=None,
          relay=True, relay_share=0.6, aux=()):
    """aux: more signals of the same module, observed together with `obs` while proving and dropped
    from the result (see project()). Observing a counter together with the state machine that
    drives it is what lets the closure show which counter values and steps can never occur."""
    cert = _prove(spec, list(obs) + list(aux), work, depth, shallow, max_states, budget, ks, grow, reset_cycles, check_ms, windows, max_len,
                  inject, do_replay, sim_runs, sim_cycles, stim, relay, relay_share)
    return project(cert, len(obs)) if aux else cert


def _prove(spec, obs, work, depth, shallow, max_states, budget, ks, grow, reset_cycles, check_ms, windows, max_len, inject, do_replay,
           sim_runs, sim_cycles, stim, relay, relay_share):
    t0 = time.time()
    left = lambda: budget - (time.time() - t0)  # noqa: E731
    work = Path(work).resolve()
    if work.exists():
        shutil.rmtree(work)
    model = Model(spec, work, inject=inject)
    k = Kernel(model, obs, reset_cycles=reset_cycles, check_ms=check_ms)
    k.witness_init()
    entry = k.entry_states(max_states)
    loc = k.closure(entry, max_states) if entry else None
    comp = {"status": "bounded", "k": None, "method": None}
    U, stop = set(), "depth"
    if loc:
        Sc, Ec = loc
        comp = {"status": "proven", "k": 0, "method": "closure of one-step successors from arbitrary states"}
    # S: random simulation. Cheap, deep, and every pair it shows is real.
    conflicts, sim_pairs = [], 0
    sims = simulate(k, work / "sim", runs=sim_runs, cycles=sim_cycles, stim=stim) if sim_runs else []
    for tr in sims:
        tid, last_new = len(k.traces), None
        for t in range(k.R, len(tr["obs"]) - 1):
            p = (tr["obs"][t], tr["obs"][t + 1])
            if None in p:
                continue
            if loc and p not in Ec and list(p) not in conflicts:
                conflicts.append(list(p))  # the simulator shows a pair the proof excludes
            if p not in k.E:
                k.E[p] = (tid, t)
                last_new = t
        if last_new is not None:
            n = last_new + 2
            if any(x is None for x in tr["obs"][k.R:n]):
                for p in [p for p, (ti, _) in k.E.items() if ti == tid]:
                    del k.E[p]  # an unknown value on the way: not usable as a replayable trace
                continue
            k.traces.append({"obs": tr["obs"][:n], "inputs": {x: v[:n] for x, v in tr["inputs"].items()}, "init_regs": {}, "init_mems": {},
                             "origin": "simulation"})
            sim_pairs += sum(1 for ti, _ in k.E.values() if ti == tid)
    if not loc and len(k.states()) > max_states:
        raise Refuse(f"more than {max_states} observed states; propose predicates instead of raw values")
    if conflicts:
        comp = {"status": "refuted", "k": None, "method": "simulation shows pairs outside the proven closure", "conflicts": conflicts[:20]}
    # W: BMC from reset. With a closure it only needs to be shallow; without one it is all there is.
    quiet, last = 0, -1
    while k.depth < k.R + (shallow if loc else depth):
        if left() < 0:
            stop = "budget"
            break
        if loc and Ec <= set(k.E):
            stop = "all edges witnessed"
            break
        if k.witness_step(max_states) != "ok":
            stop = "solver gave up"
            break
        quiet = quiet + 1 if len(k.E) == last else 0
        last = len(k.E)
        if not loc and quiet >= 2 and k.E:
            for kk in ks:
                if k.depth - k.R >= kk + 1 and k.induct(k.E, kk)[0] == "proven":
                    comp = {"status": "proven", "k": kk, "method": "k-induction"}
                    break
            if comp["status"] == "proven":
                stop = "closed"
                break
            quiet = -3
    bmc_depth = k.depth - k.R
    relay_stats = None
    if loc:
        if relay and sims and do_replay and left() > 0:
            # Edges whose only trace so far does not replay from reset with inputs alone (it needs a
            # chosen power-up state, or the simulator does not reproduce it at all) are searched
            # again together with the edges that have no trace: a trace from reset is better evidence.
            _, remap0, v0, keep0, _, _ = confirm(k, work / "pre")
            stash = {p: k.E.pop(p) for p in [p for p, (tid, _) in k.E.items() if not v0[p] or remap0[tid] in keep0]}
            if Ec - set(k.E):
                t_end = time.time() + max(relay_share * left(), 0)
                relay_stats = relay_phase(k, list(sims), Ec, work / "relay", lambda: t_end - time.time())
                relay_stats["searched_again"] = len(stash)
                relay_stats["replaced"] = sum(1 for p in stash if p in k.E)
            for p, v in stash.items():
                k.E.setdefault(p, v)
        # continue from the traces found so far, window by window, towards edges still unwitnessed
        for D in windows:
            stack = list(range(len(k.traces)))
            while stack and left() > 0:
                targets = Ec - set(k.E)
                if not targets:
                    break
                tid = stack.pop()
                if len(k.traces[tid]["obs"]) + D > max_len:
                    continue
                if k.extend(tid, targets, D) == "found":
                    stack += [tid, len(k.traces) - 1]
            if not (Ec - set(k.E)):
                stop = "all edges witnessed"
                break
        rest = Ec - set(k.E)
        U = set(rest)
        if rest and k.E and left() > 0:
            # can some of the unwitnessed edges be proven unreachable? k-induction over the witnessed graph
            for kk in sorted(ks, reverse=True):
                if bmc_depth < kk + 1:
                    continue
                st, U2 = k.induct(k.E, kk, grow=len(rest))
                if st == "proven" and U2 <= rest:
                    U = U2
                    comp["tightened"] = {"k": kk, "removed": len(rest) - len(U2)}
                    break
    elif comp["status"] != "proven" and k.E and left() > 0:
        for kk in sorted(ks, reverse=True):
            if bmc_depth < kk + 1:
                continue
            st, U2 = k.induct(k.E, kk, grow=grow)
            if st == "proven":
                U, comp = U2, {"status": "proven", "k": kk, "method": "k-induction"}
                break
    U -= set(k.E)
    comp.update(depth=bmc_depth, stopped=stop, undetermined=len(U), pairs_from_simulation=sim_pairs)
    if relay_stats:
        comp["relay"] = relay_stats
    traces, remap, verdict, keep, how, rep = confirm(k, work, do_replay)
    probe = same_design(k, work / "probe") if do_replay else {"error": "not run"}
    edges = []
    for (a, b), (tid, t) in sorted(k.E.items()):
        ok, i = verdict[(a, b)], remap[tid]
        e = {"src": a, "dst": b, "status": "witnessed" if ok else "model-witness", "trace": i, "step": t, "replay": ok}
        if ok and i in keep:
            e["needs_power_up"] = True  # happens from reset only with the power-up state the trace lists
        edges.append(e)
    for a, b in sorted(U):
        edges.append({"src": a, "dst": b, "status": "undetermined"})
    # What the certificate carries is what its reader replays: a power-up state only where an edge
    # needs it, under every name the simulator may know the register by.
    out_traces, reg_w = [], dict(model.regs)
    for i, tr in enumerate(traces):
        o = {"obs": tr["obs"], "inputs": tr["inputs"], "init_regs": {}, "init_mems": {}, "origin": tr.get("origin", "bmc")}
        if i in keep:
            for n, v in tr["init_regs"].items():
                for a in [n] + model.aliases.get(n, []):
                    o["init_regs"][a] = v
                    reg_w[a] = model.regs[n]
            o["init_mems"] = tr.get("init_mems") or {}
        out_traces.append(o)
    # a state is witnessed only through an edge the simulator confirmed; one that only a model trace
    # or the closure reaches stays undetermined
    wst = {x for p, ok in verdict.items() if ok for x in p}
    states = [{"value": v, "status": "witnessed" if v in wst else "undetermined", "entry": bool(entry and v in entry)}
              for v in sorted(k.states() | {x for p in U for x in p} | set(entry or []))]
    return {
        "schema": "proven-graph-0.1", "design": spec.get("design"), "top": model.design_top,
        "scope": {"instance": model.scope, "module": model.sim_top, "parameters": model.sim_params},
        "observation": [{"signal": n, "width": w} for n, w in k.obs], "width": k.W,
        "assumptions": {"clock": {"port": model.clock, "edge": "negedge" if model.negedge else "posedge"},
                        "reset": k.rst, "reset_cycles": k.R, "reset_after_release": "never reasserted",
                        # inputs that look like a reset but are driven freely: if one of them is the real reset,
                        # the design is assumed to be reset at random and started another way than intended
                        "reset_like_inputs_left_free": sorted(n for n in k.ins if model.inputs[n] == 1 and RESET_RE.search(n)
                                                              and n not in {r["port"] for r in k.rst}),
                        "inputs": "unconstrained", "unknown_values": "any value", "power_up": "RTL initial values, otherwise any value",
                        "configuration": "as synthesized: SYNTHESIS and YOSYS defined, simulator-only macros not taken",
                        "source_order": model.source_order, "macros": "carried from file to file, as in Yosys"},
        "states": states, "edges": edges, "completeness": comp,
        "traces": out_traces,
        "widths": {"inputs": {n: model.inputs[n] for n in k.ins}, "regs": reg_w, "mems": model.mems},
        "replay": {"mode": how, "traces": rep, "with_power_up_state": sorted(keep), "same_design": probe},
        "engine": {"model": "yosys write_smt2", "solver": "z3 " + z3.get_version_string(), "queries": k.queries,
                   "flip_flops": model.nff, "seconds": round(time.time() - t0, 1), "files_dropped": model.dropped},
    }


def main(argv):
    spec = json.loads(Path(argv[1]).read_text())
    cert = prove(spec, spec["observe"], argv[2], **spec.get("options", {}))
    Path(argv[2], "cert.json").write_text(json.dumps(cert, indent=1))
    e = cert["edges"]
    print(cert["completeness"], "states", len(cert["states"]), "edges", len(e),
          {s: sum(1 for x in e if x["status"] == s) for s in ("witnessed", "model-witness", "undetermined")}, cert["engine"])


if __name__ == "__main__":
    import sys
    try:
        main(sys.argv)
    except Refuse as ex:
        print("REFUSED:", ex)
