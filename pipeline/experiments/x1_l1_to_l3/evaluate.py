"""Run bridge + renderers over the eval set and score every drawing the same way.

    uv run --with nodejs-wheel python pipeline/experiments/x1_l1_to_l3/evaluate.py \
        --version v1 --split dev            # writes runs/x1eval/<version>/<split>/...

Each step runs in its own subprocess with a timeout, so one hanging layout cannot stop the
run. Per (design, renderer) it records status plus svgmetric numbers, normalised per net.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
L1 = ROOT / "layers/l1_extract"
sys.path.insert(0, str(HERE))
import svgmetric  # noqa: E402

RENDERERS = {
    "paper": None,
    "elk_part": "elk_part+native+we+implicit",
    "elk": "elk+native+we+implicit",
    "elk_r12": "elk_part+native+we+implicit",  # R12 bundling applied to the input, then ELK
    "system": None,  # system-view grammar (system.py)
}
STEP = """
import json, sys
sys.path.insert(0, {here!r})
what, name, out = sys.argv[1], sys.argv[2], sys.argv[3]
if what == "bridge":
    import bridge
    it = json.loads(sys.argv[4])
    d, h, m = bridge.build(it)
    for k, v in (("diagram", d), ("hints", h), ("meta", m)):
        with open(f"{{out}}/{{name}}.{{k}}.json", "w", encoding="utf-8") as fh:
            fh.write(json.dumps(v, indent=1, ensure_ascii=False))
    print(json.dumps({{"blocks": len(d["blocks"]), "nets": len(d["nets"]), "view": m.get("view")}}))
elif what == "system":
    import system
    ld = lambda k: json.load(open(f"{{out}}/{{name}}.{{k}}.json", encoding="utf-8"))
    svg, m = system.render(ld("diagram"), ld("hints"), ld("meta"), title=name)
    open(f"{{out}}/{{name}}.system.svg", "w", encoding="utf-8").write(svg)
    print(json.dumps(m))
elif what == "paper":
    import paper
    ld = lambda k: json.load(open(f"{{out}}/{{name}}.{{k}}.json"))
    svg, m = paper.render(ld("diagram"), ld("hints"), ld("meta"), title=name)
    open(f"{{out}}/{{name}}.paper.svg", "w", encoding="utf-8").write(svg)
    print(json.dumps(m))
else:
    import draw_l3
    from pathlib import Path
    l3 = draw_l3.l3
    raw = json.load(open(f"{{out}}/{{name}}.diagram.json"))
    if what == "elk_r12":
        import paper
        meta = json.load(open(f"{{out}}/{{name}}.meta.json"))
        raw = paper.bundle(raw, meta["kinds"], meta)
        keep_p = ("id", "owner_block_id", "direction", "width", "class")
        raw["ports"] = [{{k: p[k] for k in keep_p}} for p in raw["ports"]]
        raw["nets"] = [{{k: v for k, v in n.items() if k != "members"}} for n in raw["nets"]]
        used = {{n["source"] for n in raw["nets"]}}
        used |= {{t for n in raw["nets"] for t in n["targets"]}}
        raw["ports"] = [p for p in raw["ports"] if p["id"] in used]
    d = l3.spec.Diagram.model_validate(raw)
    h = json.load(open(f"{{out}}/{{name}}.hints.json"))
    svg, m, rt = l3.draw(d, h, sys.argv[4], title=name)
    open(f"{{out}}/{{name}}.{{what}}.svg", "w", encoding="utf-8").write(svg)
    m["roundtrip"] = len(rt)
    print(json.dumps(m))
""".format(here=str(HERE))  # noqa: UP032


def step(args: list[str], timeout: int) -> tuple[str, dict | str, float]:
    t0 = time.perf_counter()
    try:
        r = subprocess.run(
            [sys.executable, "-c", STEP, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=L1,
            env={**os.environ, "PYTHONUTF8": "1"},
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        return "timeout", "", time.perf_counter() - t0
    dt = time.perf_counter() - t0
    if r.returncode:
        err = (r.stderr.strip().splitlines() or ["?"])[-1]
        return "error", err[:200], dt
    return "ok", json.loads(r.stdout.strip().splitlines()[-1]), dt


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--split", default="dev", choices=["dev", "test", "indicator", "fresh", "all"])
    ap.add_argument("--only", default="")
    ap.add_argument("--renderers", default=",".join(RENDERERS))
    a = ap.parse_args()
    items = json.loads((HERE / "eval_set.json").read_text(encoding="utf-8"))
    items = [it for it in items if a.split == "all" or it["split"] == a.split]
    if a.only:
        items = [it for it in items if it["name"] in a.only.split(",")]
    out = ROOT / "runs/x1eval" / a.version / a.split
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for it in items:
        name = it["name"]
        design = {"name": name, "top": it["top"], "files": [str(L1 / f) for f in it["files"]]}
        st, res, dt = step(["bridge", name, str(out), json.dumps(design)], 600)
        base = {"design": name, "category": it["category"], "split": it["split"]}
        if st != "ok":
            rows.append({**base, "renderer": "bridge", "status": st, "error": res})
            print(name, "bridge", st, res)
            continue
        nb = res["blocks"]
        for r in a.renderers.split(","):
            row = {
                **base,
                "renderer": r,
                "blocks": nb,
                "bridge_nets": res["nets"],
                "view": res.get("view"),
            }
            if nb < 2:
                rows.append({**row, "status": "nothing_to_draw"})
                continue
            args = [r, name, str(out)] + ([RENDERERS[r]] if RENDERERS[r] else [])
            st, m, dt = step(args, 240)
            row.update(status=st, seconds=round(dt, 1))
            if st == "ok":
                svg = (out / f"{name}.{r}.svg").read_text(encoding="utf-8")
                sm = svgmetric.metrics(svg)
                row.update(
                    sm,
                    cross_per_net=round(sm["cross"] / max(1, res["nets"]), 2),
                    len_per_net=round(sm["length"] / max(1, res["nets"])),
                    own={
                        k: m.get(k) for k in ("unrouted", "block_ov", "roundtrip", "size") if k in m
                    },
                )
            else:
                row["error"] = m
            rows.append(row)
            print(name, r, st, {k: row.get(k) for k in ("cross_per_net", "overlap", "through")})
    # merge with an earlier run of other renderers / designs in this version+split
    rf = out / "results.json"
    if rf.exists():
        done = {(r["design"], r["renderer"]) for r in rows}
        old = [
            r
            for r in json.loads(rf.read_text(encoding="utf-8"))
            if (r["design"], r["renderer"]) not in done
            and (not a.only or r["design"] not in a.only.split(","))
        ]
        rows = old + rows
    rf.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    summarize(rows)


def summarize(rows: list[dict]) -> None:
    designs = sorted({r["design"] for r in rows})
    print(f"\n{len(designs)} designs")
    for r in RENDERERS:
        rs = [x for x in rows if x["renderer"] == r]
        ok = [x for x in rs if x["status"] == "ok"]
        clean = [x for x in ok if x["overlap"] == 0 and x["through"] == 0]
        cpn = sorted(x["cross_per_net"] for x in ok)
        med = cpn[len(cpn) // 2] if cpn else None
        bad = sum(x["overlap"] + x["through"] for x in ok)
        print(
            f"{r:9s} drawn {len(ok)}/{len(designs)}  clean {len(clean)}  "
            f"median cross per bridge net {med}  overlap+through {bad}  "
            f"fail {[x['design'] + ':' + x['status'] for x in rs if x['status'] != 'ok']}"
        )


if __name__ == "__main__":
    main()
