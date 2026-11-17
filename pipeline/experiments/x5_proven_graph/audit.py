"""x5 audit: which verification was actually carried out on which certificate, and with which code.

    python audit.py OUT

Nothing is recomputed that needs a solver. The audit reads what run.py and post.py left behind and
answers one question per certificate and per kind of verification: pass, FAIL, or NOT RUN. A result
counts only if it carries the hash of the certificate file that is there now and the hash of the
source files that are here now; a result left over from another certificate or another version
of the code is NOT RUN. What needs no tool is recomputed here independently: the certificate's
internal consistency, the projection of a supporting edge set, the drawing read back from the SVG.

Writes OUT/audit.json. Exit status 0 only if nothing is FAIL or NOT RUN.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]  # noqa: E731
CODE = {f: sha(HERE / f) for f in ("prove.py", "check.py", "guards.py", "attack.py", "post.py", "run.py")}
PASS, FAIL, NOT = "pass", "FAIL", "NOT RUN"


def bound(stamp, cert_sha):
    """Is a result file about this certificate and made by this code? -> None, or why not."""
    if not stamp:
        return "result carries no stamp"
    if stamp.get("cert_sha") != cert_sha:
        return "result is about another version of the certificate"
    if stamp.get("code") != CODE:
        return "result was made by another version of the code"
    return None


def consistency(cert):
    """The certificate against itself. -> list of problems."""
    bad = []
    W = cert["width"]
    if W != sum(o["width"] for o in cert["observation"]):
        bad.append("width does not match the observation")
    sv = {s["value"] for s in cert["states"]}
    pairs = [(e["src"], e["dst"]) for e in cert["edges"]]
    if len(set(pairs)) != len(pairs):
        bad.append("an edge is listed twice")
    R = cert["assumptions"]["reset_cycles"]
    for e in cert["edges"]:
        if e["src"] not in sv or e["dst"] not in sv:
            bad.append(f"edge {e['src']}->{e['dst']} uses a state that is not listed")
        if e["status"] == "witnessed":
            tr = cert["traces"][e["trace"]] if 0 <= e.get("trace", -1) < len(cert["traces"]) else None
            t = e.get("step", -1)
            if tr is None or t < R or t + 1 >= len(tr["obs"]) or (tr["obs"][t], tr["obs"][t + 1]) != (e["src"], e["dst"]):
                bad.append(f"witnessed edge {e['src']}->{e['dst']}: its trace does not show the pair at the stated step")
            elif bool(e.get("needs_power_up")) != bool(tr.get("init_regs") or tr.get("init_mems")):
                bad.append(f"witnessed edge {e['src']}->{e['dst']}: power-up flag and trace disagree")
    wit_states = {x for e in cert["edges"] if e["status"] == "witnessed" for x in (e["src"], e["dst"])}
    for s in cert["states"]:
        if (s["status"] == "witnessed") != (s["value"] in wit_states):
            bad.append(f"state {s['value']} is called {s['status']}, which the witnessed edges do not bear out")
    comp = cert["completeness"]
    if comp.get("undetermined") != sum(e["status"] == "undetermined" for e in cert["edges"]):
        bad.append("undetermined count does not match the edges")
    sup = comp.get("support")
    if sup:
        sh_ = sup["width"] - W
        have = set(pairs)
        proj = {(a >> sh_, b >> sh_) for a, b in sup["pairs"]}
        if sup["observation"][:len(cert["observation"])] != cert["observation"] or sh_ < 0:
            bad.append("supporting observation does not extend the observation")
        if proj - have:
            bad.append(f"{len(proj - have)} supporting pairs project outside the edges")
        if have - proj:
            bad.append(f"{len(have - proj)} edges have no supporting pair")
    return bad


def audit_one(d, row):
    cert = json.loads((d / "cert.json").read_text())
    cs = sha(d / "cert.json")
    it = {}
    e = cert["edges"]
    n = lambda s: sum(x["status"] == s for x in e)  # noqa: E731
    info = {"design": cert["design"], "id": cert.get("id"), "cert_sha": cs, "source": cert.get("source"), "states": len(cert["states"]), "edges": len(e),
            "witnessed": n("witnessed"), "undetermined": n("undetermined"), "model_witness": n("model-witness"),
            "needs_power_up": sum(1 for x in e if x.get("needs_power_up")), "completeness": cert["completeness"]["status"],
            "method": cert["completeness"].get("method"), "aux": bool(cert["completeness"].get("support")),
            "source_order": cert["assumptions"].get("source_order"), "seconds": cert["engine"].get("seconds")}
    # 0. produced by this prover
    pc = cert["engine"].get("code")
    it["prover version"] = ({"status": PASS} if pc == {k: CODE[k] for k in ("prove.py", "run.py")} else
                            {"status": NOT, "detail": "certificate carries no prover stamp" if not pc else "certificate was made by another version of the prover"})
    # 0b. the simulator elaborated the same design as the model
    sd = cert.get("replay", {}).get("same_design")
    if not sd or "error" in sd:
        it["same design in both tools"] = {"status": NOT, "detail": (sd or {}).get("error", "certificate carries no structural cross-check")}
    else:
        u = sd["unknown_to_simulator"]
        it["same design in both tools"] = {"status": PASS if not u else FAIL,
                                           "detail": f"{sd['registers']} registers, {sd['memories']} memories" + (f"; unknown to the simulator: {u[:8]}" if u else "")}
    # 0c. the reset protocol was decided, not guessed while another candidate was left free
    A = cert["assumptions"]
    if "reset_like_inputs_left_free" not in A:
        it["reset protocol"] = {"status": NOT, "detail": "certificate does not list the reset-like inputs left free"}
    else:
        free = A["reset_like_inputs_left_free"]
        chosen = "、".join(f"{r['port']} {'active low' if r['active_low'] else 'active high'} ({r.get('how', '')})" for r in A["reset"]) or "none"
        explicit = A["reset"] and all(str(r.get("how", "")).startswith(("proposed", "given")) for r in A["reset"])
        if free and not explicit:
            it["reset protocol"] = {"status": FAIL, "detail": f"reset {chosen} was chosen by name, while {free} also look like a reset and are driven freely"}
        else:
            it["reset protocol"] = {"status": PASS, "detail": f"reset {chosen}" + (f"; left free on purpose: {free}" if free else "")}
    # 1. internal consistency, recomputed here
    bad = consistency(cert)
    it["certificate consistent"] = {"status": PASS if not bad else FAIL, "detail": "; ".join(bad[:4])}
    # 2, 3. independent checker
    chk = json.loads((d / "check.json").read_text()) if (d / "check.json").exists() else None
    why = "no check.json" if chk is None else bound(chk.get("stamp"), cs)
    if why:
        it["witnesses replayed"] = it["completeness, second engine"] = {"status": NOT, "detail": why}
    else:
        w, c = chk["witnesses"], chk["completeness"]
        it["witnesses replayed"] = {"status": PASS if w["result"] == "ok" else FAIL, "detail": f"{info['witnessed']} edges, {len(cert['traces'])} traces, {w.get('mode')}"
                                    + ("" if w["result"] == "ok" else f"; unconfirmed {w.get('unconfirmed')}; {w.get('why', '')}")}
        want = "proven" if cert["completeness"]["status"] == "proven" else "bounded-ok"
        if c["result"] == want:
            it["completeness, second engine"] = {"status": PASS, "detail": f"{c.get('engine')}, induction length {c.get('step')}, {chk.get('seconds')} s"}
        elif "timeout" in str(c.get("why", "")).lower() or c["result"] == "not run":
            it["completeness, second engine"] = {"status": NOT, "detail": f"did not finish: {c.get('why')}"}
        else:
            it["completeness, second engine"] = {"status": FAIL, "detail": str(c.get("why"))}
        info["check_seconds"] = chk.get("seconds")
    # 4. names
    nm = json.loads((d / "names.json").read_text()) if (d / "names.json").exists() else None
    why = "no names.json" if nm is None else bound(nm.get("stamp"), cs)
    it["state names"] = {"status": NOT, "detail": why} if why else {"status": PASS, "detail": f"{len(nm['verified'])} of {len(nm['proposed'])} proposed names proven equal and used"}
    if not why:
        info.update(names_proposed=len(nm["proposed"]), names_verified=len(nm["verified"]))
    # 5. guard labels, only where a proposer gave labels
    spec = json.loads((d / "spec.json").read_text())
    if spec.get("l1_json"):
        g = json.loads((d / "guards" / "guards.json").read_text()) if (d / "guards" / "guards.json").exists() else None
        why = "no guards.json" if g is None else bound(g.get("stamp"), cs)
        if why:
            it["guard labels"] = {"status": NOT, "detail": why}
        else:
            t, dd = {}, {}
            for r in g["proposed"]:
                t[r["status"]] = t.get(r["status"], 0) + 1
            for r in g["derived"].get("edges", []):
                dd[r["status"]] = dd.get(r["status"], 0) + 1
            info.update(l1_labels=t, derived_labels=dd)
            it["guard labels"] = {"status": PASS, "detail": f"proposed {t}; derived {dd}"}
    else:
        it["guard labels"] = {"status": "n/a", "detail": "no labels were proposed for this machine"}
    # 6. the drawing, read back here
    if (d / "graph.svg").exists():
        svg = (d / "graph.svg").read_text()
        got = set(re.findall(r'class="edge">\s*<title>s(\d+)&#45;&gt;s(\d+)</title>', svg))
        nodes = set(re.findall(r'class="node">\s*<title>s(\d+)</title>', svg))
        ok = got == {(str(x["src"]), str(x["dst"])) for x in e if x["src"] != x["dst"]} and nodes == {str(x["value"]) for x in cert["states"]}
        it["drawing matches certificate"] = {"status": PASS if ok else FAIL, "detail": f"{len(nodes)} nodes, {len(got)} edges read back from the SVG"}
    else:
        it["drawing matches certificate"] = {"status": NOT, "detail": "no graph.svg"}
    # 7. attack
    ap = d / "attack" / "attack.json"
    st = json.loads((d / "attack" / "stamp.json").read_text()) if (d / "attack" / "stamp.json").exists() else None
    why = "no attack.json" if not ap.exists() else bound(st, cs)
    if why:
        it["attack"] = {"status": NOT, "detail": why}
    else:
        rows = json.loads(ap.read_text())
        t = {}
        for r in rows:
            key = r["kind"] + ":" + (r.get("verdict") or ("accepted" if r.get("accepted") else "REJECTED"))
            t[key] = t.get(key, 0) + 1
        info["attack"] = t
        info["attack_cases_per_kind"] = rows[0].get("cases_per_kind")
        info["attack_rejected_by"] = {}
        for r in rows[1:]:
            if r.get("rejected_by"):
                key = r["kind"] + ": " + r["rejected_by"].split(":")[0] + (": " + r["rejected_by"].split(":")[1].strip()[:40] if ":" in r["rejected_by"] else "")
                info["attack_rejected_by"][key] = info["attack_rejected_by"].get(key, 0) + 1
        surv = sum(v for k, v in t.items() if "SURVIVOR" in k)
        err = sum(v for k, v in t.items() if "ERROR" in k or "ABORTED" in k)  # no verdict: tested nothing
        base = t.get("original:accepted", 0) == 1
        tam = sum(v for k, v in t.items() if k.startswith("tamper:"))
        status = FAIL if surv or not base else (NOT if err or not tam else PASS)
        it["attack"] = {"status": status, "detail": f"{t}" + (f"; {err} cases gave no verdict (error or aborted)" if err else "") + ("" if tam else "; no tampered certificate was tried")}
    return info, it


def main(argv):
    out = Path(argv[1]).resolve()
    summ = {}
    for sp in [out / "summary.json"] + sorted(out.glob("summary_*.json")):
        if sp.exists():
            for r in json.loads(sp.read_text()):
                summ[(r["design"], r["id"])] = r
    rows, seen = [], set()
    for cp in sorted(out.glob("*/*/cert.json")):
        d = cp.parent
        if not (d / "spec.json").exists():
            continue
        info, it = audit_one(d, None)
        seen.add((info["design"], info["id"]))
        rows.append({**info, "dir": str(d), "items": it})
    missing = [{"design": k[0], "id": k[1], "status": r["status"], "reason": r.get("reason")} for k, r in sorted(summ.items()) if k not in seen]
    kinds = list(rows[0]["items"]) if rows else []
    tot = {k: {PASS: 0, FAIL: 0, NOT: 0, "n/a": 0} for k in kinds}
    for r in rows:
        for k, v in r["items"].items():
            tot[k][v["status"]] += 1
    clean = not missing and all(v[FAIL] == 0 and v[NOT] == 0 for v in tot.values())
    (out / "audit.json").write_text(json.dumps({"code": CODE, "clean": clean, "totals": tot, "without_certificate": missing, "rows": rows}, indent=1))
    for r in rows:
        marks = " ".join({PASS: "ok", FAIL: "FAIL", NOT: "----", "n/a": "n/a"}[r["items"][k]["status"]].ljust(4) for k in kinds)
        print(f'{r["id"][:34]:34s} {marks}  e{r["edges"]:3d} w{r["witnessed"]:3d} u{r["undetermined"]:2d} m{r["model_witness"]} pu{r["needs_power_up"]}')
        for k in kinds:
            if r["items"][k]["status"] in (FAIL, NOT):
                print(f'     {k}: {r["items"][k]["status"]}: {r["items"][k].get("detail")}')
    print("columns:", " | ".join(kinds))
    for k in kinds:
        print(f"  {k:32s} {tot[k]}")
    for m in missing:
        print("  NO CERTIFICATE:", m)
    print("code", CODE)
    print("AUDIT CLEAN" if clean else "AUDIT NOT CLEAN")
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
