"""x5 post-processing of every certificate under OUT: independent check, state names, guard labels,
attack, drawing.

    python post.py OUT [--jobs N] [--attack N] [--only SUBSTR]

Writes next to each cert.json: check.json, names.json, guards/guards.json, attack/attack.json,
graph.dot, graph.svg; and OUT/post.json with one row per certificate.
"""
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import time
import traceback
from multiprocessing import Pool
from pathlib import Path

import z3

sys.path.insert(0, str(Path(__file__).parent))
import check as C  # noqa: E402
import guards as G  # noqa: E402
import prove as P  # noqa: E402


def verify_names(spec, cert, names, work):
    """names: {value: text}. A name is kept only if the RTL expression of that name, compiled inside
    the scope module, is proven equal to the value. -> {value: name}"""
    W = cert["width"]
    items = [(int(v), n) for v, n in names.items() if re.fullmatch(r"`?[A-Za-z_]\w*", n)]
    if not items:
        return {}
    ok = {}

    def attempt(sub):
        inj = "\n".join(f"(* keep *) wire x5_n{i} = (({n}) == {W}'d{v});" for i, (v, n) in sub)
        try:
            m = P.Model(spec, Path(work) / f"n{len(sub)}_{sub[0][0]}", inject={cert["scope"]["module"]: inj})
        except P.Refuse:
            return None
        k = P.Kernel(m, [o["signal"] for o in cert["observation"]], extra=[f"x5_n{i}" for i, _ in sub])
        f = k.frame("n")
        out = {}
        for j, (i, (v, n)) in enumerate(sub):
            s = k.solver()
            s.add(f["local"])
            s.add(z3.Not(f["x"][j]))
            if k.check(s) == z3.unsat:
                out[v] = n
        return out

    sub = list(enumerate(items))
    r = attempt(sub)
    if r is None:  # one bad name must not cost the others
        r = {}
        for one in sub:
            r.update(attempt([one]) or {})
    ok.update(r)
    return ok


def dot(cert, names, labels, max_label=46):
    name = lambda v: names.get(v) or names.get(str(v)) or str(v)  # noqa: E731
    L = ["digraph g {", '  rankdir=LR; bgcolor="white"; fontname="Helvetica"; fontsize=11; labelloc=b; labeljust=l;',
         '  node [shape=ellipse, fontname="Helvetica", fontsize=12, style=filled, fillcolor="#eef6f0", color="#1f6f43", penwidth=1.6];',
         '  edge [fontname="Helvetica", fontsize=9, color="#1c1f23", arrowsize=0.7];']
    for s in cert["states"]:
        st = 'style="filled,dashed", fillcolor="#f4f4f5", color="#8a8f98"' if s["status"] != "witnessed" else ""
        L.append(f'  s{s["value"]} [label="{html.escape(name(s["value"]))}" {st}];')
        if s["entry"]:
            L.append(f'  e{s["value"]} [shape=point, width=0.12, color="#1c1f23"]; e{s["value"]} -> s{s["value"]};')
    loops = 0
    for e in cert["edges"]:
        if e["src"] == e["dst"]:
            loops += 1
            continue
        lab = labels.get((e["src"], e["dst"]))
        txt = ""
        if lab and lab.get("label"):
            t = lab["label"]
            t = t if len(t) <= max_label else t[: max_label - 1] + "…"
            txt = t + ("" if lab["status"] == "exact" else " …")
        style = {"witnessed": "", "model-witness": 'style=dashed, color="#b45309"', "undetermined": 'style=dashed, color="#8a8f98", fontcolor="#8a8f98"'}[e["status"]]
        if e["status"] == "undetermined":
            txt = "?"
        tip = html.escape((lab or {}).get("label") or "")
        L.append(f'  s{e["src"]} -> s{e["dst"]} [label="{html.escape(txt)}", tooltip="{tip}" {", " + style if style else ""}];')
    c = cert["completeness"]
    L.append("}")
    return "\n".join(L), loops


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


def code_version():
    """Hash of every source file of the method. Each result file carries it together with the hash
    of the certificate it is about, so a result can never be counted for another certificate or
    another version of the code."""
    here = Path(__file__).parent
    return {f: sha(here / f) for f in ("prove.py", "check.py", "guards.py", "attack.py", "post.py", "run.py")}


def one(a):
    d, n_attack = Path(a[0]), a[1]
    row = {"dir": str(d)}
    try:
        cert, spec = json.loads((d / "cert.json").read_text()), json.loads((d / "spec.json").read_text())
        stamp = {"cert_sha": sha(d / "cert.json"), "code": code_version()}
        row.update(design=cert["design"], id=cert["id"], source=cert.get("source"), cert_sha=stamp["cert_sha"])
        for old in ("check.json", "names.json", "graph.svg", "graph.dot"):  # nothing from an earlier run may be mistaken for this one
            (d / old).unlink(missing_ok=True)
        for old in ("guards", "attack"):
            shutil.rmtree(d / old, ignore_errors=True)
        t0 = time.time()
        chk = C.check(spec, cert, d / "chk")
        chk["seconds"] = round(time.time() - t0, 1)
        chk["stamp"] = stamp
        (d / "check.json").write_text(json.dumps(chk, indent=1))
        row.update(check_ok=chk["ok"], check=chk["completeness"]["result"], check_why=chk["completeness"].get("why"), witnesses=chk["witnesses"]["result"],
                   check_step=chk["completeness"].get("step"), check_seconds=chk["seconds"])
        l1 = json.loads(Path(spec["l1_json"]).read_text()) if spec.get("l1_json") else None
        prop = dict(spec.get("names") or {})
        if l1:
            prop.update({str(s["value"]): s["name"] for s in l1["states"]})
        names = verify_names(spec, cert, prop, d / "names") if prop else {}
        (d / "names.json").write_text(json.dumps({"proposed": prop, "verified": names, "stamp": stamp}, indent=1))
        row.update(names_proposed=len(prop), names_verified=len(names))
        labels = {}
        if l1:
            rows = G.check_guards(spec, cert, l1, d / "guards" / "labels")
            tab = G.guard_tables(spec, cert, l1, d / "guards" / "tables")
            (d / "guards" / "guards.json").write_text(json.dumps({"proposed": rows, "derived": tab, "stamp": stamp}, indent=1))
            t, dd = {}, {}
            for r in rows:
                t[r["status"]] = t.get(r["status"], 0) + 1
            for r in tab["edges"]:
                dd[r["status"]] = dd.get(r["status"], 0) + 1
                labels[(r["src"], r["dst"])] = r
            row.update(l1_labels=t, derived_labels=dd)
        g, loops = dot(cert, {int(k): v for k, v in names.items()}, labels)
        (d / "graph.dot").write_text(g)
        subprocess.run(["dot", "-Tsvg", "-o", str(d / "graph.svg"), str(d / "graph.dot")], capture_output=True, timeout=120)
        row["self_loops"] = loops
        # the drawing is read back and compared with the certificate, so a renderer bug cannot hide
        svg = (d / "graph.svg").read_text() if (d / "graph.svg").exists() else ""
        got = set(re.findall(r'class="edge">\s*<title>s(\d+)&#45;&gt;s(\d+)</title>', svg))
        nodes = set(re.findall(r'class="node">\s*<title>s(\d+)</title>', svg))
        row["render_roundtrip"] = (got == {(str(e["src"]), str(e["dst"])) for e in cert["edges"] if e["src"] != e["dst"]}
                                   and nodes == {str(x["value"]) for x in cert["states"]})
        if n_attack:  # every certificate is attacked; a slow one gets fewer cases, never none
            import attack as A
            A.main(["attack", str(d / "spec.json"), str(d / "cert.json"), str(d / "attack"), str(n_attack), str(a[2]), str(a[3])])
            (d / "attack" / "stamp.json").write_text(json.dumps(stamp))
            t = {}
            for r in json.loads((d / "attack" / "attack.json").read_text()):
                key = r["kind"] + ":" + (r.get("verdict") or ("accepted" if r.get("accepted") else "REJECTED"))
                t[key] = t.get(key, 0) + 1
            row["attack"] = t
    except Exception as ex:  # noqa: BLE001
        row.update(error=repr(ex)[:300], tb=traceback.format_exc()[-500:])
    print(json.dumps(row), flush=True)
    return row


def main(argv):
    out = Path(argv[1]).resolve()
    opt = dict(zip(argv[2::2], argv[3::2]))
    dirs = sorted(p.parent for p in out.glob("*/*/cert.json") if (p.parent / "spec.json").exists())
    if "--only" in opt:
        dirs = [d for d in dirs if opt["--only"] in str(d)]
    with Pool(int(opt.get("--jobs", 4))) as pool:
        rows = pool.map(one, [(str(d), int(opt.get("--attack", 0)), int(opt.get("--attack-heavy", 2)), float(opt.get("--heavy-seconds", 90)))
                              for d in dirs], chunksize=1)
    name = "post.json" if "--only" not in opt else "post_" + re.sub(r"\W+", "_", opt["--only"]) + ".json"
    (out / name).write_text(json.dumps(rows, indent=1))  # a partial rerun never overwrites the full table


if __name__ == "__main__":
    main(sys.argv)
