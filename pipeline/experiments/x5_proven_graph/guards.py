"""x5 guard check: is the condition written on an edge true?

    python guards.py SPEC.json CERT.json L1_FSM.json WORK

A guard label is a proposal (from the L1 extractor here; an LLM or a person may write them too).
Each label g on an edge A -> B is compiled into the scope module as a wire and two statements are
tried from an arbitrary state, reset inactive:
  sufficient   obs = A and g           implies  next obs = B
  necessary    obs = A and next obs = B implies  one of the labels written on A -> B
Both proven: `exact`. Only the first: `sufficient` (the edge can also be taken another way).
Neither: `unproven` and the label must not be drawn as fact. A counterexample is kept.
The check is over every state with that observation, reachable or not, so a label that only
holds on reachable states is reported unproven rather than accepted.
"""
import json
import sys
from pathlib import Path

import z3

sys.path.insert(0, str(Path(__file__).parent))
import prove as P  # noqa: E402


def _build(spec, cert, guards, work):
    """Model with one wire per guard. Guards that do not compile are found by bisection."""
    mod = cert["scope"]["module"]
    good, bad = [], []

    def attempt(idx, tag):
        inj = "\n".join(f"(* keep *) wire x5_g{i} = |({guards[i]});" for i in idx)
        try:
            return P.Model(spec, Path(work) / f"m_{tag}", inject={mod: inj})
        except P.Refuse:
            return None

    todo = [list(range(len(guards)))]
    n = 0
    while todo:
        idx = todo.pop()
        if not idx:
            continue
        n += 1
        if attempt(idx, n) is not None:
            good += idx
        elif len(idx) == 1 or n > 24:
            bad += idx
        else:
            todo += [idx[: len(idx) // 2], idx[len(idx) // 2:]]
    good.sort()
    model = attempt(good, "final") if good else None
    return model, good, bad


def check_guards(spec, cert, l1, work, check_ms=30000):
    val = {s["id"]: s["value"] for s in l1["states"]}
    trans = [t for t in l1["transitions"] if t["src"] in val and t["dst"] in val]
    texts = sorted({t["guard"] for t in trans if t.get("guard") and t.get("guard_kind") in ("expr", "cube", "always")})
    model, good, bad = _build(spec, cert, texts, work)
    rows = []
    if model is None:
        return [{"src": val[t["src"]], "dst": val[t["dst"]], "guard": t.get("guard"), "status": "not compiled"} for t in trans]
    wire = {texts[i]: f"x5_g{i}" for i in good}
    k = P.Kernel(model, [o["signal"] for o in cert["observation"]], reset_cycles=cert["assumptions"]["reset_cycles"],
                 check_ms=check_ms, extra=[wire[texts[i]] for i in good])
    gi = {texts[i]: j for j, i in enumerate(good)}
    s, a, b = k.solver(), k.frame("ga"), k.frame("gb")
    for fr in (a, b):
        s.add(fr["local"])
        s.add(z3.Not(fr["is"]))
        if k.rst:
            s.add(fr["rn"])
    s.add(k.trans(a, b))
    by = {}
    for t in trans:
        by.setdefault((val[t["src"]], val[t["dst"]]), []).append(t)
    for (A, B), ts in sorted(by.items()):
        gs = [a["x"][gi[t["guard"]]] for t in ts if t.get("guard") in gi]
        nec = None
        if gs and len(gs) == len(ts):
            s.push()
            s.add(a["o"] == A, b["o"] == B, z3.Not(z3.Or(gs)))
            nec = k.check(s) == z3.unsat
            s.pop()
        for t in ts:
            row = {"src": A, "dst": B, "guard": t.get("guard"), "kind": t.get("guard_kind")}
            if t.get("guard") not in gi:
                row["status"] = "not compiled" if t.get("guard") in texts else "no label"
            else:
                s.push()
                s.add(a["o"] == A, a["x"][gi[t["guard"]]], b["o"] != B)
                r = k.check(s)
                if r == z3.sat:
                    row["counterexample_next"] = P._val(s.model(), b["o"])
                s.pop()
                row["status"] = ("exact" if nec else "sufficient") if r == z3.unsat else ("unproven" if r == z3.sat else "solver gave up")
            rows.append(row)
    return rows


def _qm(on, dc, n):
    """Prime-implicant cover of the minterms `on` (don't-cares `dc`) over n variables. Cubes are
    strings over 0/1/-. Greedy cover; any cover built from implicants of on|dc is correct."""
    terms = {format(m, f"0{n}b") for m in on | dc}
    primes = set()
    while terms:
        nxt, used = set(), set()
        tl = sorted(terms)
        for i, a in enumerate(tl):
            for b in tl[i + 1:]:
                d = [j for j in range(n) if a[j] != b[j]]
                if len(d) == 1 and "-" not in (a[d[0]], b[d[0]]):
                    nxt.add(a[:d[0]] + "-" + a[d[0] + 1:])
                    used |= {a, b}
        primes |= terms - used
        terms = nxt
    cov = lambda c, m: all(x in ("-", y) for x, y in zip(c, format(m, f"0{n}b")))  # noqa: E731
    left, out = set(on), []
    while left:
        best = max(sorted(primes), key=lambda c: (sum(cov(c, m) for m in left), c.count("-")))
        out.append(best)
        left -= {m for m in left if cov(best, m)}
    return out


def _text(cubes, atoms):
    def lit(i, v):
        a = atoms[i]
        simple = a.replace("_", "").replace(".", "").isalnum()
        return (a if simple else f"({a})") if v == "1" else (f"!{a}" if simple else f"!({a})")
    parts = [" && ".join(lit(i, v) for i, v in enumerate(c) if v != "-") or "1" for c in cubes]
    return " || ".join(parts if len(parts) == 1 else [f"({p})" if " && " in p else p for p in parts])


def guard_tables(spec, cert, l1, work, check_ms=30000, max_atoms=8, max_rows=400):
    """For every state: the proposed labels of its outgoing edges are atoms; the solver enumerates
    every (atom valuation, next observation) that can occur from an arbitrary state. A valuation
    with one possible successor decides the edge. The label of A -> B is rebuilt from exactly
    those valuations, so it is proven by construction; valuations with several successors are
    reported as `also depends on other signals`."""
    val = {s["id"]: s["value"] for s in l1["states"]}
    trans = [t for t in l1["transitions"] if t["src"] in val and t["dst"] in val]
    texts = sorted({t["guard"] for t in trans if t.get("guard") and t.get("guard_kind") in ("expr", "cube") and t["guard"] != "1"})
    model, good, bad = _build(spec, cert, texts, work)
    if model is None:
        return {"error": "no proposed label compiles", "edges": []}
    k = P.Kernel(model, [o["signal"] for o in cert["observation"]], reset_cycles=cert["assumptions"]["reset_cycles"],
                 check_ms=check_ms, extra=[f"x5_g{i}" for i in good])
    gi = {texts[i]: j for j, i in enumerate(good)}
    s, a, b = k.solver(), k.frame("ta"), k.frame("tb")
    for fr in (a, b):
        s.add(fr["local"])
        s.add(z3.Not(fr["is"]))
        if k.rst:
            s.add(fr["rn"])
    s.add(k.trans(a, b))
    out = []
    for A in sorted({e["src"] for e in cert["edges"]}):
        atoms = sorted({t["guard"] for t in trans if val[t["src"]] == A and t.get("guard") in gi})[:max_atoms]
        xs = [a["x"][gi[g]] for g in atoms]
        n = len(atoms)
        rows, complete = {}, True
        s.push()
        s.add(a["o"] == A)
        for _ in range(max_rows):
            r = k.check(s)
            if r != z3.sat:
                complete = r == z3.unsat
                break
            m = s.model()
            c = sum(P._val(m, x) << (n - 1 - i) for i, x in enumerate(xs))
            B = P._val(m, b["o"])
            rows.setdefault(c, set()).add(B)
            s.add(z3.Or([x != z3.BoolVal(bool((c >> (n - 1 - i)) & 1)) for i, x in enumerate(xs)] + [b["o"] != B]))
        else:
            complete = False
        s.pop()
        dc = set(range(1 << n)) - set(rows) if complete else set()
        for B in sorted({e["dst"] for e in cert["edges"] if e["src"] == A}):
            sure = {c for c, bs in rows.items() if bs == {B}}
            maybe = {c for c, bs in rows.items() if B in bs and len(bs) > 1}
            row = {"src": A, "dst": B, "atoms": atoms, "enumeration_complete": complete}
            if not complete:
                row.update(label=None, status="not derived")
            elif not n:
                row.update(label=None if maybe else "1", status="exact" if not maybe else "no atoms proposed")
            else:
                row["label"] = _text(_qm(sure, dc, n), atoms) if sure else None
                row["status"] = "exact" if sure and not maybe else ("partial" if sure else "depends on other signals")
                if maybe:
                    row["also_when"] = _text(_qm(maybe, dc, n), atoms)
            out.append(row)
    return {"edges": out, "atoms_not_compiled": [texts[i] for i in bad]}


if __name__ == "__main__":
    spec, cert, l1 = (json.loads(Path(p).read_text()) for p in sys.argv[1:4])
    rows = check_guards(spec, cert, l1, Path(sys.argv[4]) / "labels")
    tab = guard_tables(spec, cert, l1, Path(sys.argv[4]) / "tables")
    Path(sys.argv[4], "guards.json").write_text(json.dumps({"proposed": rows, "derived": tab}, indent=1))
    t, d = {}, {}
    for r in rows:
        t[r["status"]] = t.get(r["status"], 0) + 1
    for r in tab["edges"]:
        d[r["status"]] = d.get(r["status"], 0) + 1
    print(json.dumps({"design": spec.get("design"), "id": cert.get("id"), "proposed_labels": t, "derived_labels": d}))
