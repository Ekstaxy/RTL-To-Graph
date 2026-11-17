"""x5 gap closing: edges without a witness proven impossible by PDR, with the invariant carried.

The closure from arbitrary states leaves edges that are possible from SOME state but have no trace
from reset. Most of them are impossible from every reachable state, and showing that needs an
invariant nobody wrote down. PDR (IC3, as implemented in ABC) finds one: it proves that the
monitored design never takes an edge outside a given set and returns an inductive invariant.

Nothing here is trusted. The invariant goes into the certificate as cubes over named registers,
and the checker proves the edge set together with that invariant by temporal induction in Yosys's
own SAT pass (MiniSat), a different solver and encoding. An invariant that is wrong, or that this
module translated wrongly, makes that proof fail; it can never make a false edge set pass.

The netlist is the checker's own (`check.design`), written as AIGER with `-zinit`: registers the
RTL does not initialise get their power-up value from an extra input in the first cycle, and a
latch named `ninitff` is 0 in that cycle and 1 afterwards. A cube that needs `ninitff = 0` speaks
only of the first cycle and is dropped; the checker covers that cycle by the monitor's own initial
values.
"""
import re
import shutil
import time
from pathlib import Path

import check as C
import prove as P

ABC = "yosys-abc"


def build(spec, cert, pairs, work, timeout=900):
    """AIGER of design + monitor whose single output is 1 when an edge outside `pairs` is taken."""
    work = Path(work).resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    prefixes, top = C.design(spec, cert, work, cert["observation"], cert["width"], pairs, bad=True)
    ys = (prefixes[0] + f"cd {top}\ndelete -port o:*\nexpose x5_mon.bad\nopt_clean\ncd ..\n"
          "techmap\nopt_clean\naigmap\nopt_clean\nwrite_aiger -zinit -map aig.map x.aig\n")
    (work / "aig.ys").write_text(ys)
    rc, log = P.sh([P.YOSYS, "-q", "-s", "aig.ys"], cwd=work, timeout=timeout)
    (work / "aig.log").write_text(log)
    if rc != 0 or not (work / "x.aig").exists():
        return None, "yosys could not write the AIGER: " + (log.strip().splitlines() or ["?"])[-1][:200]
    return work, None


def run(work, seconds):
    """-> ('proved', cubes over latch indices) | ('cex', frame) | ('unknown', why)."""
    rc, log = P.sh([ABC, "-c", f"read_aiger x.aig; print_stats; pdr -T {int(seconds)} -d"], cwd=work, timeout=seconds + 120)
    (work / "abc.log").write_text(log)
    if "Property proved" in log:
        return "proved", _pla(work / "x_inv.pla")
    m = re.search(r"was asserted in frame (\d+)", log)
    if m:
        return "cex", int(m.group(1))
    return "unknown", ("time limit" if rc == 124 or "timeout" in log.lower() else (log.strip().splitlines() or ["?"])[-1][:160])


def _pla(path):
    lab, cubes = [], []
    for ln in path.read_text().splitlines():
        if ln.startswith(".ilb"):
            lab = [int(x[2:]) for x in ln.split()[1:]]
        elif ln and ln[0] in "01-":
            bits = ln.split()[0]
            cubes.append([(lab[i], int(c)) for i, c in enumerate(bits) if c != "-"])
    return cubes


def _latches(work):
    """latch index -> [(bit, name)], and the index of the first-cycle latch."""
    names, ninit = {}, None
    for ln in (work / "aig.map").read_text().splitlines():
        f = ln.split()
        if f[0] == "latch":
            names.setdefault(int(f[1]), []).append((int(f[2]), f[3]))
        elif f[0] == "ninitff":
            ninit = int(f[1])
    return names, ninit


def translate(work, cubes, widths):
    """Cubes over AIGER latches -> cubes over named bits, as `check.monitor` reads them.
    widths: register widths the model knows; a name outside it gets the width the AIGER map shows.
    -> (cubes, signals {name: width}, untranslatable). A cube with a latch that has no usable name
    is reported, not guessed."""
    names, ninit = _latches(work)
    seen_w = {}
    for nm in names.values():
        for b, n in nm:
            seen_w[n] = max(seen_w.get(n, 0), b + 1)
    out, bad, sigs = [], 0, {}
    for cube in cubes:
        lits, skip = [], False
        for idx, v in cube:
            if idx == ninit:
                if v == 0:
                    skip = True  # speaks only of the first cycle
                    break
                continue
            nm = names.get(idx, [])
            mon = [(b, n.split(".", 1)[1]) for b, n in nm if n.startswith("x5_mon.") and n.split(".", 1)[1] in C.MON_REGS]
            des = [(b, n) for b, n in nm if not n.startswith(("x5_mon.", "$")) and re.fullmatch(r"[A-Za-z_][\w$.\[\]]*", n)]
            if mon:
                lits.append(["monitor", mon[0][1], mon[0][0], v])
            elif des:
                # a register the model knows by name first: its width is certain
                b, n = min(des, key=lambda x: (x[1] not in widths, x[1].count("."), len(x[1]), x[1]))
                sigs[n] = int(widths.get(n, seen_w[n]))
                lits.append(["design", n, b, v])
            else:
                skip, bad = True, bad + 1
                break
        if not skip:
            out.append(sorted(lits))
    used = {x[1] for cube in out for x in cube if x[0] == "design"}
    return out, {n: w for n, w in sigs.items() if n in used}, bad


def close(spec, cert, work, seconds=300, per_edge=120, budget=900, self_check=True):
    """Try to prove the undetermined edges of `cert` impossible. -> (certificate, report).
    The certificate comes back unchanged unless the checker's own induction accepts the result."""
    t0 = time.time()
    work = Path(work).resolve()
    U = [(e["src"], e["dst"]) for e in cert["edges"] if e["status"] == "undetermined"]
    rep = {"undetermined": len(U), "removed": [], "runs": []}
    if not U:
        return cert, rep
    every = [(e["src"], e["dst"]) for e in cert["edges"]]
    blocked, removed, signals = [], [], {}
    widths = (cert.get("widths") or {}).get("regs") or {}

    def attempt(drop, tag, secs):
        w, err = build(spec, cert, [p for p in every if p not in drop], work / tag)
        if err:
            rep["runs"].append({"edges": [list(p) for p in drop], "result": "error", "why": err})
            return None
        r, x = run(w, secs)
        row = {"edges": [list(p) for p in drop], "result": r}
        if r == "proved":
            cubes, sigs, bad = translate(w, x, widths)
            row.update(cubes=len(x), translated=len(cubes), untranslatable=bad)
            rep["runs"].append(row)
            if bad or any(signals.get(n, wd) != wd for n, wd in sigs.items()):
                return None
            signals.update(sigs)
            return cubes
        row.update(frame=x) if r == "cex" else row.update(why=x)
        rep["runs"].append(row)
        return None

    got = attempt(U, "all", seconds)
    if got is not None:
        blocked, removed = got, list(U)
    else:
        # one edge at a time: each run proves that edge never happens; the invariants of all runs hold
        # together, and together they exclude every edge that was proved
        for j, p in enumerate(U):
            if time.time() - t0 > budget:
                rep["stopped"] = "budget"
                break
            got = attempt([p], f"e{j}", per_edge)
            if got is not None:
                blocked += got
                removed.append(p)
    if not removed:
        return cert, rep
    seen, uniq = set(), []
    for cube in blocked:
        k = tuple(map(tuple, cube))
        if k not in seen:
            seen.add(k)
            uniq.append(cube)
    new = narrow(cert, removed, {"engine": "abc pdr", "signals": dict(sorted(signals.items())), "blocked": uniq, "removed_edges": sorted(list(p) for p in removed)})
    if self_check:
        c = C.completeness(spec, new, work / "self_check", maxsteps=4)
        rep["self_check"] = c
        if c.get("result") != "proven":
            rep["dropped"] = "the checker's induction did not accept the invariant"
            return cert, rep
    rep["removed"] = sorted(list(p) for p in removed)
    rep["seconds"] = round(time.time() - t0, 1)
    return new, rep


def narrow(cert, removed, inv):
    """The certificate without the edges proved impossible, and without states only they touched."""
    rm = {tuple(p) for p in removed}
    edges = [e for e in cert["edges"] if (e["src"], e["dst"]) not in rm]
    used = {x for e in edges for x in (e["src"], e["dst"])}
    states = [s for s in cert["states"] if s["value"] in used or s.get("entry")]
    comp = {k: v for k, v in cert["completeness"].items() if k != "support"}
    comp["undetermined"] = sum(e["status"] == "undetermined" for e in edges)
    comp["invariant"] = inv
    comp["method"] = (comp.get("method") or "") + "; edges without a witness proven impossible by PDR, invariant checked by induction"
    return dict(cert, edges=edges, states=states, completeness=comp)
