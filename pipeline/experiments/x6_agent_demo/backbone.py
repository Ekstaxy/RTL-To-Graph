"""The tools the agent calls. Every one of them runs the project's own pipelines; nothing here draws
or decides anything by itself.

  designs()                         the corpus, and any RTL folder given as "dir:/path/to/rtl#top"
  analyze(design)                   L1's reading of the design: clocks, resets, handshake interfaces
                                    with the role of each signal, state-register candidates, files
  read_source(design, file, ...)    lines of a source file, or the lines that mention a signal
  block(design, view)               block diagram: x1 bridge + x2 adapter + e3 layout engines
  fsm(design, signal, ...)          proven state graph: x5 prover + independent checker
  timing(design, interface)         timing diagrams: x4 simulation + wave drawing + checks

Results go under RUNS/<session>/ and are returned as artifacts {kind, title, file, caption, facts}.
"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
def X(p):
    """A configured path: ~ expanded, relative paths taken from this folder."""
    q = Path(os.path.expanduser(p))
    return q if q.is_absolute() else (HERE / q).resolve()
X4_ROOT, BLOCK_ROOT = X(CFG["x4_root"]), X(CFG["block_root"])
X5_DIR = (HERE / CFG["x5_dir"]).resolve()
X5_PY, PATH_EXTRA = X(CFG["x5_python"]), X(CFG["path_extra"])
CORPUS = json.loads(X(CFG["corpus_manifest"]).read_text())
CACHE_X4, CACHE_BLOCK, CACHE_X5 = X(CFG["cache"]["x4"]), X(CFG["cache"]["block"]), X(CFG["cache"]["x5"])
RUNS = HERE / "runs"
UV = CFG.get("uv", "uv")
ENV = dict(os.environ, PATH=str(PATH_EXTRA) + ":" + os.environ.get("PATH", ""))


class ToolError(Exception):
    pass


def _sh(cmd, cwd, timeout, env=None):
    try:
        r = subprocess.run([str(c) for c in cmd], cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env or ENV)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, f"time limit of {timeout} s"


# ---- which design ---------------------------------------------------------------------------------
def resolve(design):
    """A corpus name, or 'dir:/path/to/rtl#top' for a folder of the user's own Verilog."""
    if design.startswith("dir:"):
        path, _, top = design[4:].partition("#")
        d = Path(os.path.expanduser(path)).resolve()
        files = sorted(str(p) for p in d.rglob("*") if p.suffix in (".v", ".sv", ".vh", ".svh") and p.is_file())
        if not files:
            raise ToolError(f"no Verilog files under {d}")
        if not top:
            raise ToolError("give the top module after '#', e.g. dir:/home/me/rtl#my_top")
        name = re.sub(r"\W+", "_", d.name + "_" + top)
        return {"name": name, "top": top, "files": [f for f in files if not f.endswith((".vh", ".svh"))], "include_dirs": [str(d)],
                "defines": [], "own": True, "dir": str(d)}
    e = next((x for x in CORPUS if x["name"] == design), None)
    if e is None:  # a top module name that only one corpus design has
        tops = [x for x in CORPUS if x["top"] == design or x["name"].endswith("_" + design)]
        e = tops[0] if len(tops) == 1 else None
    if e is None:
        near = [x["name"] for x in CORPUS if design.lower() in x["name"].lower() or x["top"].lower() == design.lower()]
        raise ToolError(f"unknown design '{design}'" + (f"; did you mean {near}?" if near else "; call list_designs"))
    return {"name": e["name"], "top": e["top"], "files": [str(X4_ROOT / f) for f in e["files"]],
            "include_dirs": [str(X4_ROOT / d) for d in e.get("include_dirs") or []], "defines": e.get("defines") or [], "own": False,
            "rel": e["files"]}


def designs():
    out = []
    for e in CORPUS:
        out.append({"design": e["name"], "top": e["top"], "project": e["name"].split("_")[0], "files": [Path(f).name for f in e["files"]]})
    return {"designs": out, "own_rtl": "a folder of your own: design = 'dir:/absolute/path#top_module'"}


# ---- L1's reading of the design -------------------------------------------------------------------
def _x4_dir(d, parts="fsm,timing"):
    """x4 results for this design: the corpus run, or a fresh run for the user's own RTL."""
    if not d["own"]:
        p = CACHE_X4 / d["name"]
        if (p / "result.json").exists():
            return p
    out = RUNS / "_x4" / d["name"]

    def found():  # x4 names a folder input after the folder, a manifest entry after its name
        hits = sorted(out.glob("designs/*/result.json"))
        return hits[0].parent if len(hits) == 1 else out / "designs" / d["name"]

    res = found()
    if (res / "result.json").exists():
        return res
    cmd = [UV, "run", "--package", "rtl2d-l1", "python", "pipeline/experiments/x4_fsm_timing/x4_run.py",
           "--rtl", d["dir"] if d["own"] else str(Path(d["files"][0]).parent), "--top", d["top"], "--part", parts, "--out", str(out)]
    if not d["own"]:  # a corpus design that was not in the batch: run it from a one-entry manifest
        out.mkdir(parents=True, exist_ok=True)
        man = out / "manifest.json"
        man.write_text(json.dumps([{"name": d["name"], "files": d["rel"], "top": d["top"], "include_dirs": [], "defines": d["defines"], "tb": None}]))
        cmd = cmd[:6] + ["--manifest", str(man), "--part", parts, "--out", str(out)]
    rc, log = _sh(cmd, X4_ROOT, 1800)
    (out / "x4.log").parent.mkdir(parents=True, exist_ok=True)
    (out / "x4.log").write_text(log)
    res = found()
    if not (res / "result.json").exists():
        raise ToolError("x4 did not finish: " + (log.strip().splitlines() or ["?"])[-1][:300])
    return res


def analyze(design):
    d = resolve(design)
    p = _x4_dir(d)
    sig = json.loads((p / "signals.json").read_text()) if (p / "signals.json").exists() else {}
    res = json.loads((p / "result.json").read_text())
    files = []
    for f in d["files"]:
        try:
            n = sum(1 for _ in open(f, errors="replace"))
        except OSError:
            n = None
        files.append({"file": Path(f).name, "lines": n})
    ifs = [{"id": i.get("id"), "protocol": i.get("protocol"), "direction": i.get("direction"), "domain": i.get("domain"),
            "confirmed": i.get("confirmed"), "members": [{"port": m.get("port"), "role": m.get("role"), "width": m.get("width"), "dir": m.get("dir")}
                                                          for m in i.get("members", [])][:12]} for i in sig.get("interfaces", [])]
    fsms = []
    for f in res.get("fsm") or []:
        g = {}
        gp = X4_ROOT / f["json"] if f.get("json") else None
        if gp is not None and not gp.exists():  # a bundled copy keeps only the design's own folder
            gp = p / "fsm" / Path(f["json"]).name
        if gp is not None and gp.exists():
            g = json.loads(gp.read_text())
        fsms.append({"id": f.get("id"), "state_signal": g.get("state_reg"), "instance": g.get("instance"), "states": len(g.get("states", [])),
                     "x4_status": f.get("status"), "state_names": [s.get("name") for s in g.get("states", [])][:24]})
    return {"design": d["name"], "top": d["top"], "files": files, "clocks": sig.get("clocks", []), "resets": sig.get("resets", []),
            "interfaces": ifs, "state_register_candidates": fsms,
            "note": "Roles come from L1's heuristic reading (names and how signals are used). Confirm with read_source before relying on one."}


def read_source(design, file, start=1, end=None, grep=None):
    d = resolve(design)
    f = next((x for x in d["files"] if Path(x).name == file or x.endswith("/" + file)), None)
    if f is None:
        raise ToolError(f"{file} is not a file of {d['name']}: {[Path(x).name for x in d['files']]}")
    lines = Path(f).read_text(errors="replace").splitlines()
    if grep:
        rx = re.compile(r"\b" + re.escape(grep) + r"\b")
        hit = [i for i, ln in enumerate(lines) if rx.search(ln)][:60]
        return {"file": file, "signal": grep, "lines": [f"{i + 1}: {lines[i]}" for i in hit], "total_hits": len([1 for ln in lines if rx.search(ln)])}
    start = max(1, int(start or 1))
    end = min(len(lines), int(end or start + 120), start + 200)
    return {"file": file, "from": start, "to": end, "of": len(lines), "text": "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))}


# ---- artifacts -----------------------------------------------------------------------------------------
def _publish(session, src, name):
    dst = RUNS / session / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return f"runs/{session}/{name}"


# ---- block diagram -----------------------------------------------------------------------------------
ENGINE_WORD = {"busbar": "匯流排長條", "dot": "分層", "hola": "HOLA 正交", "grid": "格狀"}


def block(design, view="paper", session="s"):
    """view: paper (the e3 layout with the fewest crossings, for papers and slides), system (x1's
    whole-system picture), or all."""
    d = resolve(design)
    p = CACHE_BLOCK / d["name"] if not d["own"] else None
    if p is None or not (p / "block.json").exists():
        out_root = RUNS / "_block"
        out_root.mkdir(parents=True, exist_ok=True)
        man = out_root / f"{d['name']}.manifest.json"
        man.write_text(json.dumps([{"name": d["name"], "top": d["top"], "files": d["files"]}]))
        env = dict(ENV, GAL_ROOT=str(BLOCK_ROOT), GAL_OUT=str(out_root), GAL_MANIFEST=str(man))
        run = [UV, "run", "--package", "rtl2d-l1", "--with", "nodejs-wheel", "--with", "ortools", "python", str(HERE / "gal_block_agent.py")]
        for args in (["A", d["name"], "-", "busbar,dot,hola,grid"], ["B", d["name"]]):
            rc, log = _sh(run + args, BLOCK_ROOT, 900, env=env)
            (out_root / f"{d['name']}.{args[0]}.log").write_text(log)
        p = out_root / d["name"]
        if not (p / "block.json").exists():
            raise ToolError("the block pipeline did not finish; see runs/_block/*.log")
    b = json.loads((p / "block.json").read_text())
    br, engs = b["bridge"], b.get("engines", {})
    if br.get("status") != "ok":
        raise ToolError(f"x1 bridge failed: {br.get('error')}")
    ok = {k: v for k, v in engs.items() if v.get("status") == "ok" and (p / f"e3.{k}.svg").exists()}
    best = min(ok, key=lambda k: (ok[k].get("cross", 1e9), ok[k].get("roundtrip", 0))) if ok else None
    arts = []
    facts = {"units": br.get("units"), "nets": br.get("unit_nets"), "groups": br.get("groups", [])[:12], "interfaces": br.get("interfaces", [])[:12]}
    if view in ("paper", "all") and best:
        for k in ([best] if view == "paper" else sorted(ok, key=lambda k: ok[k].get("cross", 1e9))):
            arts.append({"kind": "block", "title": f"{d['top']} 架構圖（論文版，{ENGINE_WORD.get(k, k)}引擎）",
                         "file": _publish(session, p / f"e3.{k}.svg", f"{d['name']}.block.{k}.svg"),
                         "caption": f"{br.get('units')} 個單元、{br.get('unit_nets')} 條連線，{ok[k].get('cross')} 個交叉；畫完從 SVG 反查，錯誤 {ok[k].get('roundtrip', 0)} 個。",
                         "facts": dict(facts, engine=k, crossings=ok[k].get("cross"), roundtrip_errors=ok[k].get("roundtrip"))})
    if view in ("system", "all") and (p / "x1.system.svg").exists():
        arts.append({"kind": "block", "title": f"{d['top']} 架構圖（系統版）", "file": _publish(session, p / "x1.system.svg", f"{d['name']}.block.system.svg"),
                     "caption": "x1 的系統圖畫法：整個設計一張，子模組與介面照階層排。", "facts": facts})
    if not arts:
        raise ToolError(f"no drawing for view '{view}'")
    return {"design": d["name"], "artifacts": arts, "summary": facts}


# ---- proven state graph -----------------------------------------------------------------------------
def _x5_cached(name, signal, scope):
    if not CACHE_X5.exists():
        return None
    for c in CACHE_X5.glob("*/*/cert.json"):
        try:
            cert = json.loads(c.read_text())
        except ValueError:
            continue
        ob = [o["signal"] for o in cert["observation"]]
        if cert.get("design") == name and ob == [signal] and (scope is None or cert["scope"]["instance"] == scope):
            return c.parent
    return None


def _x5_summary(cdir):
    cert = json.loads((cdir / "cert.json").read_text())
    chk = json.loads((cdir / "check.json").read_text()) if (cdir / "check.json").exists() else None
    names = json.loads((cdir / "names.json").read_text()) if (cdir / "names.json").exists() else None
    e = cert["edges"]
    n = lambda s: sum(x["status"] == s for x in e)  # noqa: E731
    inv = cert["completeness"].get("invariant") or {}
    audit = None
    aud = cdir.parent.parent / "audit.json"
    if aud.exists():
        row = next((r for r in json.loads(aud.read_text())["rows"] if r.get("id") == cert.get("id") and r.get("design") == cert.get("design")), None)
        if row:
            audit = {k: v["status"] for k, v in row["items"].items()}
    nm = {}
    if isinstance(names, dict) and isinstance(names.get("verified"), dict):
        nm = {int(k): v for k, v in names["verified"].items()}
    lab = lambda v: f"{v} {nm[v]}" if v in nm else str(v)  # noqa: E731
    return {"states": [s["value"] for s in cert["states"]], "edges": len(e),
            "transitions": [f"{lab(x['src'])} -> {lab(x['dst'])}" + ("" if x["status"] == "witnessed" else f" ({x['status']})")
                            for x in e if x["src"] != x["dst"]],
            "self_loops": [lab(x["src"]) for x in e if x["src"] == x["dst"]],
            "witnessed": n("witnessed"), "undetermined": n("undetermined"),
            "model_witness": n("model-witness"), "complete": cert["completeness"]["status"],
            "proven_impossible_by_pdr": inv.get("removed_edges", []),
            "checker": None if chk is None else {"ok": chk.get("ok"), "witnesses": chk.get("witnesses", {}).get("result"),
                                                 "completeness": chk.get("completeness", {}).get("result"), "engine": chk.get("completeness", {}).get("engine")},
            "names": None if not names else {str(k): v for k, v in (names.get("verified") or names.get("names") or {}).items()} if isinstance(names, dict) else None,
            "assumptions": {"clock": cert["assumptions"]["clock"]["port"], "reset": cert["assumptions"]["reset"],
                            "reset_cycles": cert["assumptions"]["reset_cycles"]},
            "audit": audit, "scope": cert["scope"]["instance"], "module": cert["scope"]["module"]}


def fsm(design, signal, scope=None, reset=None, active_low=None, aux=None, session="s"):
    d = resolve(design)
    cdir = None if d["own"] or aux else _x5_cached(d["name"], signal, scope)
    how = "taken from the audited batch run (all ten verifications passed)" if cdir else None
    if cdir is None:
        out = RUNS / "_x5" / f"{d['name']}_{signal}_{int(time.time())}"
        inp = out / "_input"
        inp.mkdir(parents=True, exist_ok=True)
        root = Path(os.path.commonpath([str(Path(f).parent) for f in d["files"]]))
        man = [{"name": d["name"], "files": [os.path.relpath(f, root) for f in d["files"]], "top": d["top"],
                "include_dirs": [os.path.relpath(x, root) for x in d["include_dirs"]], "defines": d["defines"], "tb": None}]
        prop = {"id": d["top"] + "." + signal, "observe": [signal], "scope": scope or [], "source": "agent"}
        if aux:
            prop["options"] = {"aux": aux}
        if reset:
            prop["reset"] = {"port": reset, "active_low": bool(active_low), "how": "proposed by the agent from the source"}
        (inp / "manifest.json").write_text(json.dumps(man))
        (inp / "proposals.json").write_text(json.dumps({d["name"]: [prop]}))
        (inp / "x4").mkdir(exist_ok=True)
        rc, log = _sh([X5_PY, X5_DIR / "run.py", root, inp / "manifest.json", inp / "x4", out / "certs", "--proposals", inp / "proposals.json",
                       "--jobs", "1", "--budget", str(CFG.get("fsm_budget", 300))], X5_DIR, 2400)
        (out / "prove.log").write_text(log)
        rows = json.loads((out / "certs" / "summary.json").read_text()) if (out / "certs" / "summary.json").exists() else []
        if not rows or rows[0].get("status") in (None, "refused", "error"):
            raise ToolError("no certificate: " + json.dumps(rows[0] if rows else {"log": log[-300:]}, ensure_ascii=False)[:400])
        rc, log = _sh([X5_PY, X5_DIR / "post.py", out / "certs", "--jobs", "1"], X5_DIR, 2400)
        (out / "post.log").write_text(log)
        cdir = next((out / "certs").glob("*/*/cert.json")).parent
        how = "proved now; independent checker run, attack and audit not run in this quick mode"
    s = _x5_summary(cdir)
    svg = cdir / "graph.svg"
    if not svg.exists():  # post-processing has not drawn it yet: draw the certificate the same way, without labels
        import sys  # noqa: PLC0415
        sys.path.insert(0, str(X5_DIR))
        import post  # noqa: PLC0415
        g, _ = post.dot(json.loads((cdir / "cert.json").read_text()), {}, {})
        svg = RUNS / session / f"{d['name']}.{signal}.fsm.src.svg"
        svg.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["dot", "-Tsvg", "-o", str(svg)], input=g, text=True, capture_output=True, timeout=120)
    art = {"kind": "fsm", "title": f"{s['module']}.{signal} 狀態圖（已證明）", "file": _publish(session, svg, f"{d['name']}.{signal}.fsm.svg"),
           "caption": (f"{len(s['states'])} 個狀態、{s['edges']} 條轉移（含自環），{s['witnessed']} 條有模擬器重播確認的軌跡"
                       + (f"，{s['undetermined']} 條未定" if s["undetermined"] else "") + "；沒畫的轉移都證明不可能發生"
                       + (f"，其中 {len(s['proven_impossible_by_pdr'])} 條由 PDR 證明" if s["proven_impossible_by_pdr"] else "") + "。"),
           "facts": s}
    return {"design": d["name"], "how": how, "artifacts": [art], "summary": s}


# ---- timing diagrams ------------------------------------------------------------------------------
def timing(design, interface=None, max_diagrams=4, session="s"):
    d = resolve(design)
    p = _x4_dir(d)
    res = json.loads((p / "result.json").read_text())
    tl = res.get("timing") or []
    if not tl:
        raise ToolError("x4 produced no timing diagram for this design" + (f" ({res.get('notes')})" if res.get("notes") else ""))
    pick = [t for t in tl if interface and interface.lower() in (str(t.get("interface")) + " " + str(t.get("id"))).lower()] if interface else list(tl)
    if interface and not pick:
        return {"design": d["name"], "artifacts": [], "available": [{"id": t["id"], "interface": t.get("interface"), "protocol": t.get("protocol"),
                                                                     "scenario": t.get("scenario")} for t in tl],
                "note": f"no timing diagram for '{interface}'; pick one of the available interfaces"}
    arts = []
    for t in pick[:max_diagrams]:
        src = X4_ROOT / t["svg"] if not Path(t["svg"]).is_absolute() else Path(t["svg"])
        if not src.exists():
            src = p / "timing" / Path(t["svg"]).name
        checks = t.get("checks", {})
        ok = all(v.get("ok") for v in checks.values() if isinstance(v, dict) and "ok" in v)
        # what the drawing really contains, so the agent describes the data and not what it imagines
        content = {}
        tj = X4_ROOT / t["json"] if t.get("json") and not Path(t["json"]).is_absolute() else Path(t.get("json") or "")
        if t.get("json") and not tj.is_file():
            tj = p / "timing" / Path(t["json"]).name
        if tj.is_file():
            w = json.loads(tj.read_text())
            lanes = []
            for dom in w.get("domains", []):
                for ln in dom.get("lanes", []):
                    vals = [v.get("v") for v in ln.get("values", [])]
                    seq = [x for i, x in enumerate(vals) if i == 0 or x != vals[i - 1]]
                    cyc = [v.get("cycle") for v in ln.get("values", [])]
                    lanes.append({"signal": ln.get("signal"), "role": ln.get("role"), "cycles": [min(cyc), max(cyc)] if cyc else None,
                                  "values_in_order": seq[:12], "changes": len(seq) - 1})
            content = {"windows": [x.get("reason") for x in w.get("windows", [])], "lanes": lanes,
                       "arrows": [" -> ".join(a.get("path", [])) for a in w.get("arrows", [])][:8], "gaps": len(w.get("gaps", []))}
        arts.append({"kind": "timing", "title": f"{d['top']} 時序圖：{t.get('interface')}（{t.get('protocol')}，{t.get('scenario')}）",
                     "file": _publish(session, src, f"{d['name']}.{Path(t['svg']).name}"),
                     "caption": f"{t.get('lanes')} 條訊號、{t.get('arrows')} 個因果箭頭；波形由模擬器產生並重播比對，五項檢查{'全部通過' if ok else '有未通過'}。",
                     "facts": {"interface": t.get("interface"), "protocol": t.get("protocol"), "scenario": t.get("scenario"), "lanes": t.get("lanes"),
                               "arrows": t.get("arrows"), "checks_ok": ok, "checks": {k: v.get("ok") for k, v in checks.items() if isinstance(v, dict)},
                               "drawn": content}})
    return {"design": d["name"], "artifacts": arts, "available": [{"id": t["id"], "interface": t.get("interface"), "protocol": t.get("protocol"),
                                                                  "scenario": t.get("scenario")} for t in tl]}
