"""x5 attack: try to make the independent checker accept a certificate that is false.

    python attack.py SPEC.json CERT.json WORK [N]

A. Tampered certificates against the original RTL. Each one states something false, so the checker
   must reject it: a real edge removed, an edge that does not exist added as witnessed, an edge
   pointed at another state, an undetermined edge promoted to witnessed.
B. The original certificate against mutated RTL (one small change near the observed register:
   a negated condition, a swapped operator, another constant). The mutant's own graph is proved
   first. If it has a witnessed edge the certificate lacks, or lacks an edge the certificate
   calls witnessed, the certificate is false for that RTL and the checker must reject it.
A false certificate the checker accepts is a SURVIVOR: a hole in the method.
"""
import copy
import json
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check as C  # noqa: E402
import prove as P  # noqa: E402


def tampered(cert, rng, n):
    E = cert["edges"]
    pairs = {(e["src"], e["dst"]) for e in E}
    vals = [s["value"] for s in cert["states"]]
    wit = [e for e in E if e["status"] == "witnessed"]
    out = []
    for e in rng.sample(wit, min(n, len(wit))):
        m = copy.deepcopy(cert)
        m["edges"] = [x for x in m["edges"] if (x["src"], x["dst"]) != (e["src"], e["dst"])]
        out.append((f"remove {e['src']}->{e['dst']}", m))
    # the same lie told consistently: the traces that pass through the edge are dropped too, and the
    # edges only they witnessed are downgraded to undetermined. Only the induction can catch this one.
    R = cert["assumptions"]["reset_cycles"]
    for e in rng.sample(wit, min(max(n // 2, 1), len(wit))):
        p = (e["src"], e["dst"])
        through = {i for i, tr in enumerate(cert["traces"]) if any((tr["obs"][t], tr["obs"][t + 1]) == p for t in range(R, len(tr["obs"]) - 1))}
        keep = [i for i in range(len(cert["traces"])) if i not in through]
        remap = {old: new for new, old in enumerate(keep)}
        m = copy.deepcopy(cert)
        m["traces"] = [cert["traces"][i] for i in keep]
        edges = []
        for x in m["edges"]:
            if (x["src"], x["dst"]) == p:
                continue
            if x["status"] == "witnessed" and x["trace"] in through:
                x = {"src": x["src"], "dst": x["dst"], "status": "undetermined"}
            elif "trace" in x:
                x = dict(x, trace=remap[x["trace"]])
            edges.append(x)
        m["edges"] = edges
        sup = m["completeness"].get("support")
        if sup:  # and the finer edge set it was proved on, so that the projection still agrees
            sh = sup["width"] - m["width"]
            sup["pairs"] = [q for q in sup["pairs"] if (q[0] >> sh, q[1] >> sh) != p]
        out.append((f"remove {p[0]}->{p[1]} with the {len(through)} traces through it", m))
    absent = [(a, b) for a in vals for b in vals if (a, b) not in pairs]
    for a, b in rng.sample(absent, min(n, len(absent))):
        if not wit:
            break
        m = copy.deepcopy(cert)
        m["edges"].append(dict(rng.choice(wit), src=a, dst=b))
        out.append((f"add {a}->{b} as witnessed", m))
    for e in rng.sample(wit, min(n // 2, len(wit))):
        alt = [v for v in vals if (e["src"], v) not in pairs]
        if alt:
            m = copy.deepcopy(cert)
            for x in m["edges"]:
                if (x["src"], x["dst"]) == (e["src"], e["dst"]):
                    x["dst"] = rng.choice(alt)
            out.append((f"retarget {e['src']}->{e['dst']}", m))
    und = [e for e in E if e["status"] == "undetermined"]
    for e in rng.sample(und, min(n // 2, len(und))):
        if not wit:
            break
        m = copy.deepcopy(cert)
        for x in m["edges"]:
            if (x["src"], x["dst"]) == (e["src"], e["dst"]):
                x.update(status="witnessed", trace=wit[0]["trace"], step=wit[0]["step"])
        out.append((f"promote {e['src']}->{e['dst']}", m))
    # a trace outside the stated assumptions is not evidence, even when the simulator reproduces it
    rst = cert["assumptions"]["reset"]
    for e in rng.sample(wit, min(n // 2, len(wit))) if rst else []:
        m = copy.deepcopy(cert)
        v = m["traces"][e["trace"]]["inputs"][rst[0]["port"]]
        v[-1] = 0 if rst[0]["active_low"] else 1
        out.append((f"reset pulled again in the trace of {e['src']}->{e['dst']}", m))
    for e in rng.sample(wit, min(n // 2, len(wit))):
        m = copy.deepcopy(cert)
        ins = m["traces"][e["trace"]]["inputs"]
        free = [p for p in ins if p not in {r["port"] for r in rst}]
        if free:
            del ins[rng.choice(free)]  # an input left floating: the simulator would run on unknown values
            out.append((f"input dropped from the trace of {e['src']}->{e['dst']}", m))
    return out


def mutants(text, names, rng, n):
    """(description, mutated text) for single-line changes on lines near the observed registers."""
    lines = text.split("\n")
    hit = [i for i, l in enumerate(lines) if any(re.search(r"\b" + re.escape(x) + r"\b", l) for x in names)]
    if not hit:
        return []
    lo, hi = min(hit), max(hit)
    consts = sorted({m for i in hit for m in re.findall(r"<=\s*([A-Za-z_]\w*|\d+'[bdh][0-9a-fA-F_]+|\d+)\s*;", lines[i])})
    cand = []
    for i in range(lo, hi + 1):
        l = lines[i]
        if l.strip().startswith("//"):
            continue
        m = re.search(r"\bif\s*\((.*)\)\s*(begin)?\s*$", l)
        if m:
            cand.append((i, f"negate if @{i + 1}", l[:m.start(1)] + "!(" + m.group(1) + ")" + l[m.end(1):]))
        for a, b in (("&&", "||"), ("||", "&&"), ("==", "!="), ("!=", "==")):
            if a in l and "<=" not in l.split(a)[0][-2:]:
                cand.append((i, f"{a} to {b} @{i + 1}", l.replace(a, b, 1)))
        if i in hit:
            m = re.search(r"<=\s*([A-Za-z_]\w*|\d+'[bdh][0-9a-fA-F_]+|\d+)\s*;", l)
            if m:
                for c in consts:
                    if c != m.group(1):
                        cand.append((i, f"assign {c} instead of {m.group(1)} @{i + 1}", l[:m.start(1)] + c + l[m.end(1):]))
    rng.shuffle(cand)
    out = []
    for i, what, new in cand[:n]:
        out.append((what, "\n".join(lines[:i] + [new] + lines[i + 1:])))
    return out


def why(r):
    """Which part of the checker turned a certificate down, and how."""
    if r["ok"]:
        return None
    if not r["wellformed"]:
        return "form"
    w = r["witnesses"]
    if w["result"] != "ok":
        if w.get("traces_outside_assumptions"):
            return "witnesses: trace outside the assumptions"
        if w.get("unconfirmed"):
            return "witnesses: edge not reproduced"
        if w.get("replayed_pairs_not_listed"):
            return "witnesses: a replayed trace takes an unlisted edge"
        return "witnesses: " + str(w.get("why", "?"))[:60]
    c = r["completeness"]
    if c["result"] == "aborted":
        return "aborted"
    return "completeness: " + str(c.get("why", "?"))[:60]


def verdict_of(r, false_claim=True):
    """killed: the checker gave a verdict against a false certificate. ABORTED: it gave none."""
    if r["ok"]:
        return "SURVIVOR" if false_claim else "same graph, accepted"
    if why(r) == "aborted":
        return "ABORTED"
    return "killed" if false_claim else None


def main(argv):
    """argv: SPEC CERT WORK [N] [N_HEAVY HEAVY_SECONDS]. N cases of each kind; N_HEAVY instead when
    one run of the checker on the untouched certificate takes longer than HEAVY_SECONDS."""
    spec, cert, work = json.loads(Path(argv[1]).read_text()), json.loads(Path(argv[2]).read_text()), Path(argv[3]).resolve()
    n = int(argv[4]) if len(argv) > 4 else 8
    rng = random.Random(1)
    work.mkdir(parents=True, exist_ok=True)
    rows = []
    t0 = time.time()
    base = C.check(spec, cert, work / "base")
    base_s = round(time.time() - t0, 1)
    if len(argv) > 6 and base_s > float(argv[6]):
        n = int(argv[5])
    # The checker gets the induction length the untouched certificate needed, plus two. A bound only
    # ever turns acceptances into rejections, and without one a false certificate on a design with
    # memories drives the induction to its limit and the machine out of memory.
    steps = (base["completeness"].get("step") or 8) + 2
    rows.append({"kind": "original", "what": "untouched certificate", "accepted": base["ok"], "detail": base["completeness"], "seconds": base_s,
                 "cases_per_kind": n, "maxsteps_for_attacks": steps})
    # A tampered certificate is false by construction. One the witness check already turns down needs
    # no induction run; one that passes it must be turned down by the proof.
    for j, (what, m) in enumerate(tampered(cert, rng, n)):
        try:
            r = C.check(spec, m, work / f"a{j}", skip_proof_when_witnesses_fail=True, maxsteps=steps)
            rows.append({"kind": "tamper", "what": what, "accepted": r["ok"], "verdict": verdict_of(r), "rejected_by": why(r)})
        except Exception as ex:  # noqa: BLE001
            rows.append({"kind": "tamper", "what": what, "verdict": "ERROR", "detail": repr(ex)[:200]})
    # the source file that holds the scope module
    mod = cert["scope"]["module"]
    src = next((f for f in spec["files"] if re.search(r"^\s*module\s+" + re.escape(mod) + r"\b", Path(f).read_text(errors="replace"), re.M)), None)
    names = [o["signal"].split(".")[-1] for o in cert["observation"]]
    allp = {(e["src"], e["dst"]) for e in cert["edges"]}
    witp = {(e["src"], e["dst"]) for e in cert["edges"] if e["status"] == "witnessed"}
    for j, (what, text) in enumerate(mutants(Path(src).read_text(errors="replace"), names, rng, n) if src else []):
        d = work / f"b{j}"
        d.mkdir(exist_ok=True)
        mf = d / Path(src).name
        mf.write_text(text)
        mspec = dict(spec, files=[str(mf) if f == src else f for f in spec["files"]],
                     include_dirs=list(spec.get("include_dirs") or []) + [str(Path(src).parent)])
        row = {"kind": "mutant", "what": what}
        try:
            sup = cert["completeness"].get("support")
            aux = [o["signal"] for o in sup["observation"][len(cert["observation"]):]] if sup else []
            mc = P.prove(mspec, cert_obs(cert), d / "prove", budget=float(spec.get("attack_budget", 120)), do_replay=True, aux=aux,
                         max_states=max(64, sup["states"] * 2) if sup else 64)
        except P.Refuse as ex:
            row.update(verdict="invalid", detail=str(ex)[:100])
            rows.append(row)
            continue
        except Exception as ex:  # noqa: BLE001
            row.update(verdict="ERROR", detail="proving the mutant: " + repr(ex)[:200])
            rows.append(row)
            continue
        mall = {(e["src"], e["dst"]) for e in mc["edges"]}
        mwit = {(e["src"], e["dst"]) for e in mc["edges"] if e["status"] == "witnessed"}
        complete = mc["completeness"]["status"] == "proven"
        # Evidence from the mutant's own proof, independent of the checker: the mutant does something
        # the certificate rules out, or cannot do something the certificate says happens.
        false_claim = bool(mwit - allp) or (complete and bool(witp - mall))
        try:
            r = C.check(mspec, cert, d / "check", skip_proof_when_witnesses_fail=True, maxsteps=steps)
        except Exception as ex:  # noqa: BLE001
            row.update(verdict="ERROR", detail="checking against the mutant: " + repr(ex)[:200])
            rows.append(row)
            continue
        row.update(accepted=r["ok"], certificate_false=false_claim, new_edges=len(mwit - allp), lost_edges=len(witp - mall) if complete else None,
                   rejected_by=why(r), mutant_proof=mc["completeness"]["status"])
        if false_claim or r["ok"] or why(r) == "aborted":
            row["verdict"] = verdict_of(r, false_claim)
        elif why(r).startswith("witnesses"):
            # the mutant has the same edges, but not along the certificate's traces: what the certificate
            # says about those traces is false for this RTL, and the simulator shows it
            row["verdict"] = "trace no longer reproduces, rejected"
        else:
            row["verdict"] = "rejected, not shown false"
        rows.append(row)
    Path(work, "attack.json").write_text(json.dumps(rows, indent=1))
    t = {}
    for r in rows:
        key = r["kind"] + ":" + (r.get("verdict") or ("accepted" if r.get("accepted") else "REJECTED"))  # a refused mutant has no "accepted"
        t[key] = t.get(key, 0) + 1
    print(json.dumps({"design": spec.get("design"), "id": cert.get("id"), "tally": t}))


def cert_obs(cert):
    return [o["signal"] for o in cert["observation"]]


if __name__ == "__main__":
    main(sys.argv)
