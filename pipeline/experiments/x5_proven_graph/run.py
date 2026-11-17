"""x5 batch: prove the state graph of every proposed observation and compare with the x4 (L1) graph.

    python run.py REPO MANIFEST.json X4_DESIGNS_DIR OUT [--only NAME] [--proposals P.json] [--jobs N] [--budget S]

Proposals come from two places and are treated the same way (they only choose what to look at):
  * every state register the L1 hybrid extractor reported in X4_DESIGNS_DIR/<design>/result.json;
  * P.json: {design: [{"id": ..., "observe": [signals], "reset": {...}?, "note": ...}]} written by a
    person or an LLM for machines L1 did not find.
"""
import hashlib
import json
import sys
import traceback
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import prove as P  # noqa: E402


def candidates(repo, manifest, x4, proposals):
    out = []
    for e in manifest:
        spec = {"design": e["name"], "top": e["top"], "files": [str(repo / f) for f in e["files"]],
                "include_dirs": [str(repo / d) for d in e.get("include_dirs") or []], "defines": e.get("defines") or []}
        res = x4 / e["name"] / "result.json"
        seen = set()
        if res.exists():
            for f in json.loads(res.read_text())["fsm"]:
                gp = repo / f["json"] if f.get("json") else None
                if not gp or not gp.exists():
                    continue
                g = json.loads(gp.read_text())
                scope = g["instance"].split(".")[1:]
                rst = (g.get("checks", {}).get("yosys") or {}).get("reset")
                l1 = {"status": f["status"], "values": {s["id"]: s["value"] for s in g["states"]},
                      "edges": sorted({(s, d) for s, d in ((t["src"], t["dst"]) for t in g["transitions"])})}
                l1["edges"] = [[l1["values"][s], l1["values"][d]] for s, d in l1["edges"] if s in l1["values"] and d in l1["values"]]
                cid = f["id"] + ("@" + ".".join(g["instance"].split(".")[1:]) if "." in g["instance"] else "")
                out.append({"design": e["name"], "id": cid, "spec": dict(spec, scope=scope), "observe": [g["state_reg"]], "source": "l1",
                            "reset": rst and {"port": rst["port"], "active_low": rst["active_low"], "how": "l1: " + rst.get("how", "")},
                            "l1": l1, "l1_json": str(gp)})
        for p in proposals.get(e["name"], []):
            out.append({"design": e["name"], "id": p["id"], "spec": dict(spec, scope=p.get("scope", [])), "observe": p["observe"],
                        "source": p.get("source", "proposal"),
                        "reset": p.get("reset"), "note": p.get("note"), "options": p.get("options", {}), "names": p.get("names")})
    return out


def one(a):
    c, out, budget = a
    work = Path(out) / c["design"] / c["id"].replace("/", "_")
    spec = dict(c["spec"])
    # an L1 reset found inside a submodule names that module's port; only trust it for the top module
    if c.get("reset") and "via" not in c["reset"].get("how", ""):
        spec["reset"] = c["reset"]
    row = {"design": c["design"], "id": c["id"], "observe": c["observe"], "source": c["source"]}
    try:
        cert = P.prove(spec, c["observe"], work, budget=budget, **c.get("options", {}))
        cert["id"], cert["source"], cert["note"] = c["id"], c["source"], c.get("note")
        here = Path(__file__).parent  # which prover made this certificate: the audit compares it with the code on disk
        cert["engine"]["code"] = {f: hashlib.sha256((here / f).read_bytes()).hexdigest()[:16] for f in ("prove.py", "pdr.py", "run.py")}
        e = cert["edges"]
        row.update(status=cert["completeness"]["status"], k=cert["completeness"]["k"], depth=cert["completeness"]["depth"],
                   stopped=cert["completeness"]["stopped"], states=len(cert["states"]), edges=len(e),
                   witnessed=sum(x["status"] == "witnessed" for x in e), model_only=sum(x["status"] == "model-witness" for x in e),
                   undetermined=sum(x["status"] == "undetermined" for x in e), entry=[s["value"] for s in cert["states"] if s["entry"]],
                   replay=cert["replay"]["mode"], seconds=cert["engine"]["seconds"], reset=[r["port"] for r in cert["assumptions"]["reset"]])
        if c.get("l1"):
            mine = {(x["src"], x["dst"]) for x in e if x["src"] != x["dst"]}
            real = {(x["src"], x["dst"]) for x in e if x["src"] != x["dst"] and x["status"] != "undetermined"}
            l1 = {tuple(x) for x in c["l1"]["edges"] if x[0] != x[1]}
            cert["l1_compare"] = {"l1_status": c["l1"]["status"], "l1_only": sorted(l1 - mine), "proof_only": sorted(real - l1),
                                  "l1_states": sorted(c["l1"]["values"].values())}
            row.update(l1_status=c["l1"]["status"], l1_only=len(l1 - mine), proof_only=len(real - l1), l1_edges=len(l1))
        (work / "cert.json").write_text(json.dumps(cert, indent=1))
        (work / "spec.json").write_text(json.dumps(dict(spec, observe=c["observe"], l1_json=c.get("l1_json"), names=c.get("names")), indent=1))
    except P.Refuse as ex:
        row.update(status="refused", reason=str(ex))
    except Exception as ex:  # noqa: BLE001
        row.update(status="error", reason=repr(ex)[:300], tb=traceback.format_exc()[-600:])
    print(json.dumps(row), flush=True)
    return row


def main(argv):
    repo, man, x4, out = Path(argv[1]), json.loads(Path(argv[2]).read_text()), Path(argv[3]), Path(argv[4])
    opt = dict(zip(argv[5::2], argv[6::2]))
    props = json.loads(Path(opt["--proposals"]).read_text()) if "--proposals" in opt else {}
    cs = candidates(repo, man, x4, props)
    for c in cs:  # stimulus hints and other options for candidates that came from L1
        h = dict(props.get("_hints", {}).get(c["design"] + "/" + c["id"]) or {})
        if "reset" in h:  # a proposer may correct the reset L1 guessed; the reason goes into the certificate
            c["reset"] = h.pop("reset")
        if h:
            c["options"] = dict(c.get("options") or {}, **h)
    if "--only" in opt:
        cs = [c for c in cs if opt["--only"] in (c["design"], c["id"], c["design"] + "/" + c["id"])]
    if "--source" in opt:
        cs = [c for c in cs if c["source"] == opt["--source"]]
    out.mkdir(parents=True, exist_ok=True)
    args = [(c, str(out), float(opt.get("--budget", 300))) for c in cs]
    with Pool(int(opt.get("--jobs", 4))) as pool:
        rows = pool.map(one, args, chunksize=1)
    tag = opt.get("--tag", "summary")
    (out / f"{tag}.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main(sys.argv)
