"""x5: rebuild OUT/post.json from the files post.py left next to each certificate.

    python collect.py OUT

Use it when post.py was interrupted, or after partial reruns with --only. Nothing is recomputed
except the drawing round trip, which is cheap.
"""
import json
import re
import sys
from pathlib import Path

out = Path(sys.argv[1]).resolve()
rows = []
for cp in sorted(out.glob("*/*/cert.json")):
    d = cp.parent
    if not (d / "spec.json").exists():
        continue
    cert = json.loads(cp.read_text())
    row = {"dir": str(d), "design": cert["design"], "id": cert.get("id"), "source": cert.get("source")}
    if (d / "check.json").exists():
        chk = json.loads((d / "check.json").read_text())
        row.update(check_ok=chk["ok"], check=chk["completeness"]["result"], check_why=chk["completeness"].get("why"),
                   witnesses=chk["witnesses"]["result"])
    if (d / "names.json").exists():
        n = json.loads((d / "names.json").read_text())
        row.update(names_proposed=len(n["proposed"]), names_verified=len(n["verified"]))
    if (d / "guards" / "guards.json").exists():
        g = json.loads((d / "guards" / "guards.json").read_text())
        t, dd = {}, {}
        for r in g["proposed"]:
            t[r["status"]] = t.get(r["status"], 0) + 1
        for r in g["derived"].get("edges", []):
            dd[r["status"]] = dd.get(r["status"], 0) + 1
        row.update(l1_labels=t, derived_labels=dd)
    if (d / "graph.svg").exists():
        svg = (d / "graph.svg").read_text()
        got = set(re.findall(r'class="edge">\s*<title>s(\d+)&#45;&gt;s(\d+)</title>', svg))
        nodes = set(re.findall(r'class="node">\s*<title>s(\d+)</title>', svg))
        row["render_roundtrip"] = (got == {(str(e["src"]), str(e["dst"])) for e in cert["edges"] if e["src"] != e["dst"]}
                                   and nodes == {str(x["value"]) for x in cert["states"]})
        row["self_loops"] = sum(e["src"] == e["dst"] for e in cert["edges"])
    if (d / "attack" / "attack.json").exists():
        t = {}
        for r in json.loads((d / "attack" / "attack.json").read_text()):
            key = r["kind"] + ":" + (r.get("verdict") or ("accepted" if r.get("accepted") else "REJECTED"))
            t[key] = t.get(key, 0) + 1
        row["attack"] = t
    rows.append(row)
(out / "post.json").write_text(json.dumps(rows, indent=1))
for stale in out.glob("post_*.json"):
    stale.rename(stale.with_suffix(".json.old"))
tot = {}
for r in rows:
    for k, v in (r.get("attack") or {}).items():
        tot[k] = tot.get(k, 0) + v
print(len(rows), "rows | second engine ok", sum(bool(r.get("check_ok")) for r in rows), "| no check", sum("check_ok" not in r for r in rows),
      "| drawing ok", sum(bool(r.get("render_roundtrip")) for r in rows), "| attack", tot)
