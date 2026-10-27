"""Turn results_{a,b,c}.csv into summary.md and index.html (both under runs/).

Run: uv run --package rtl2d-l3 python layers/l3_draw/experiments/e1_layout_matrix/report.py

Ranking: inside one (input, presentation) group every combination gets a rank by the
lexicographic score (hard violations, crossings on data nets, crossings, bends, length),
scaled to 0 (best) .. 1 (worst). Presentations are ranked separately because hiding nets
removes crossings by construction.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from html import escape
from pathlib import Path
from statistics import mean, median

OUT = Path(__file__).resolve().parents[4] / "runs" / "e1_layout_matrix"
NUM = ("hard", "unrouted", "through", "overlap", "touch", "block_ov", "box_viol", "cross",
       "cross_data", "bends", "length", "width", "height", "data_sinks", "straight",
       "backward", "roundtrip", "blocks", "nets", "hidden_nets")
BASELINE = "elk+native+we+wires"


def load(tier: str) -> list[dict]:
    path = OUT / f"results_{tier}.csv"
    if not path.exists():
        return []
    rows = list(csv.DictReader(path.open()))
    for r in rows:
        for k in NUM:
            if r.get(k) not in (None, ""):
                r[k] = int(float(r[k]))
        r["seconds"] = float(r.get("seconds") or 0)
        r["placer"], r["router"], r["sides"], r["pres"] = r["combo"].split("+")
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r.get("same_as_shuffled") in (None, "")):
        key = (r["input"], r["combo"], r["hints"], r["canon"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def score(r: dict) -> tuple:
    return (r["hard"], r["cross_data"], r["cross"], r["bends"], r["length"])


def family(seed: str) -> str:
    if seed.startswith("pipe"):
        return "pipeline"
    if seed in ("rv_timer", "uart", "hmac", "plic", "ibex"):
        return "from figures"
    return "edge case" if seed.startswith("edge_") else "other shapes"


def table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def add_ranks(ok: list[dict]) -> None:
    groups = defaultdict(list)
    for r in ok:
        groups[(r["input"], r["pres"])].append(r)
    for rows in groups.values():
        scores = sorted({score(r) for r in rows})
        pos = {s: i for i, s in enumerate(scores)}
        for r in rows:
            r["rank"] = pos[score(r)] / max(1, len(scores) - 1)


def effect(ok: list[dict], key) -> list[list]:
    by = defaultdict(list)
    for r in ok:
        by[key(r)].append(r)
    rows = []
    for name, rs in by.items():
        rows.append([
            name, len(rs), pct(sum(r["hard"] == 0 for r in rs), len(rs)),
            f"{mean(r['rank'] for r in rs):.2f}", median(r["cross_data"] for r in rs),
            median(r["cross"] for r in rs), median(r["bends"] for r in rs),
            pct(sum(r["straight"] for r in rs), sum(r["data_sinks"] for r in rs)),
            f"{median(r['seconds'] for r in rs):.2f}", f"{max(r['seconds'] for r in rs):.1f}",
        ])
    return sorted(rows, key=lambda x: float(x[3]))


EFFECT_HEAD = ["level", "runs", "no hard violation", "mean rank (0 best)", "median data crossings",
               "median crossings", "median bends", "straight data sinks", "median s", "max s"]


def main() -> None:
    a, b, c = load("a"), load("b"), load("c")
    ok = [r for r in a if r["status"] == "ok"]
    add_ranks(ok)
    md = ["# e1_layout_matrix: results\n"]
    seeds = sorted({r["seed"] for r in a})
    combos = sorted({r["combo"] for r in a})
    st = defaultdict(int)
    for r in a:
        st[r["status"]] += 1
    md.append(f"Tier a: {len(seeds)} inputs x {len(combos)} combinations = {len(a)} runs. "
              f"ok {st['ok']}, not applicable (no hints) {st['n/a']}, error {st['error']}. "
              f"Round-trip failures among ok runs: {sum(r['roundtrip'] > 0 for r in ok)}.\n")

    md.append("## 1. Effect of each choice (tier a, ok runs)\n")
    for title, key in [("Placer", lambda r: r["placer"]), ("Router", lambda r: r["router"]),
                       ("Port sides", lambda r: r["sides"]), ("Presentation", lambda r: r["pres"])]:
        md.append(f"### {title}\n")
        md.append(table(EFFECT_HEAD, effect(ok, key)))
    md.append("Presentation ranks are not comparable across levels (ranked separately); "
              "compare the raw medians instead.\n")

    md.append("## 2. Placer x router\n")
    md.append(table(EFFECT_HEAD, effect(ok, lambda r: f"{r['placer']} + {r['router']}")))

    md.append("## 3. By kind of input: share of runs with no hard violation\n")
    fams = ["pipeline", "from figures", "other shapes", "edge case"]
    pr = sorted({(r["placer"], r["router"]) for r in ok})
    rows = []
    for p, ro in pr:
        row = [f"{p} + {ro}"]
        for f in fams:
            rs = [r for r in ok
                  if r["placer"] == p and r["router"] == ro and family(r["seed"]) == f]
            row.append(pct(sum(r["hard"] == 0 for r in rs), len(rs)))
        rows.append(row)
    md.append(table(["placer + router", *fams], rows))

    md.append("## 4. Best combination per input (the N4 'pick the best candidate' result)\n")
    by_in = defaultdict(list)
    for r in ok:
        by_in[r["seed"]].append(r)
    rows, wins, totals = [], defaultdict(int), defaultdict(list)
    gallery = []
    for seed in seeds:
        rs = [r for r in by_in[seed] if r["pres"] == "wires"]
        if not rs:
            continue
        best = min(rs, key=lambda r: (score(r), r["combo"]))
        base = next((r for r in rs if r["combo"] == BASELINE), None)
        for fam in {f"{r['placer']} + {r['router']}" for r in rs if score(r) == score(best)}:
            wins[fam] += 1
        if base:
            totals["baseline"].append(base)
            totals["best per input"].append(best)
        any_best = min(by_in[seed], key=lambda r: (score(r), r["combo"]))

        def fmt(r):
            return (f"{r['hard']} / {r['cross_data']} / {r['cross']} / {r['bends']} / "
                    f"{r['length']}") if r else "-"

        rows.append([seed, best["blocks"], best["nets"], f"`{best['combo']}`", fmt(best),
                     fmt(base), f"`{any_best['combo']}`", fmt(any_best)])
        gallery.append((seed, [("ELK baseline", base), ("best, all nets as wires", best),
                               ("best, any presentation", any_best)]))
    md.append("Each cell: hard violations / data crossings / crossings / bends / wire length "
              "(px).\n")
    md.append(table(["input", "blocks", "nets", "best with every net as a wire", "its score",
                     f"baseline `{BASELINE}`", "best with any presentation", "its score"], rows))
    md.append("How often each placer + router reached the best score (all nets as wires; ties "
              "count for every engine that tied):\n")
    md.append(table(["placer + router", "inputs"],
                    sorted(([k, v] for k, v in wins.items()), key=lambda x: -x[1])))
    md.append("Totals over the inputs, all nets as wires:\n")
    md.append(table(["choice", "hard violations", "data crossings", "crossings", "bends",
                     "wire length (px)"],
                    [[k, *(sum(r[m] for r in v) for m in
                           ("hard", "cross_data", "cross", "bends", "length"))]
                     for k, v in totals.items()]))

    md.append("## 5. Top single combinations (if only one could be used everywhere)\n")
    by_c = defaultdict(list)
    for r in ok:
        by_c[r["combo"]].append(r)
    rows = []
    for combo, rs in by_c.items():
        rows.append([f"`{combo}`", len(rs), pct(sum(r["hard"] == 0 for r in rs), len(rs)),
                     f"{mean(r['rank'] for r in rs):.2f}"])
    rows.sort(key=lambda x: float(x[3]))
    md.append(table(["combination", "inputs it ran on", "no hard violation", "mean rank"],
                    rows[:20]))
    md.append("Worst five:\n")
    md.append(table(["combination", "inputs it ran on", "no hard violation", "mean rank"],
                    rows[-5:]))

    errs = defaultdict(list)
    for r in a + b:
        if r["status"] == "error":
            errs[r["error"]].append(f"{r['input']} / {r['combo']}")
    md.append("## 6. Errors\n")
    md.append(table(["error", "count", "example"],
                    [[k, len(v), v[0]] for k, v in sorted(errs.items(), key=lambda x: -len(x[1]))])
              if errs else "None.\n")

    if b:
        okb = [r for r in b if r["status"] == "ok"]
        md.append("## 7. Input variants (tier b, shortlisted combinations)\n")
        combos_b = sorted({r["combo"] for r in b})
        variants = sorted({r["variant"] for r in b})
        rows = []
        for cb in combos_b:
            row = [f"`{cb}`"]
            for v in variants:
                allr = [r for r in b if r["combo"] == cb and r["variant"] == v
                        and r["hints"] == "full" and r["canon"] == "False"]
                rs = [r for r in allr if r["status"] == "ok"]
                bad = sum(r["status"] == "error" for r in allr)
                row.append(f"{pct(sum(r['hard'] == 0 for r in rs), len(rs))}"
                           + (f" ({bad} err)" if bad else ""))
            rows.append(row)
        md.append("Share of ok runs with no hard violation, per variant:\n")
        md.append(table(["combination", *variants], rows))

        md.append("### Without `kind` and `class` (`no_meta` against `base`, same seed)\n")
        rows = []
        for cb in combos_b:
            pairs = []
            for seed in seeds:
                x = {r["variant"]: r for r in okb if r["combo"] == cb and r["seed"] == seed
                     and r["hints"] == "full" and r["canon"] == "False"}
                if "base" in x and "no_meta" in x:
                    pairs.append((x["base"], x["no_meta"]))
            if pairs:
                rows.append([f"`{cb}`", len(pairs),
                             sum(p[0]["cross"] for p in pairs), sum(p[1]["cross"] for p in pairs),
                             sum(p[0]["hard"] for p in pairs), sum(p[1]["hard"] for p in pairs),
                             sum(p[0]["hidden_nets"] for p in pairs),
                             sum(p[1]["hidden_nets"] for p in pairs)])
        md.append(table(["combination", "seeds", "crossings base", "crossings no_meta",
                         "hard base", "hard no_meta", "nets hidden base", "nets hidden no_meta"],
                        rows))

        md.append("### Hints: full, partial (every second block), wrong (stages reversed), none\n")
        rows = []
        for cb in combos_b:
            if cb.split("+")[0] not in ("grid", "elk_part", "lay_ctl"):
                continue
            for how in ("full", "partial", "wrong", "none"):
                allr = [r for r in b if r["combo"] == cb and r["hints"] == how
                        and r["variant"] == "base" and r["canon"] == "False"]
                rs = [r for r in allr if r["status"] == "ok"]
                rows.append([f"`{cb}`", how, len(rs), sum(r["status"] == "n/a" for r in allr),
                             pct(sum(r["hard"] == 0 for r in rs), len(rs)),
                             sum(r["cross"] for r in rs), sum(r["backward"] for r in rs),
                             pct(sum(r["straight"] for r in rs), sum(r["data_sinks"] for r in rs))])
        md.append(table(["combination", "hints", "ok", "not applicable", "no hard violation",
                         "total crossings", "data sinks drawn right-to-left",
                         "straight data sinks"], rows))

        md.append("### Does input order change the drawing? (`base` against `shuffled`)\n")
        rows = []
        for cb in combos_b:
            row = [f"`{cb}`"]
            for canon in ("False", "True"):
                rs = [r for r in b if r["combo"] == cb and r["canon"] == canon
                      and r.get("same_as_shuffled") not in (None, "") and r["variant"] == "base"]
                same = sum(int(r["same_as_shuffled"]) for r in rs)
                row.append(f"{same}/{len(rs)}")
            rows.append(row)
        md.append(table(["combination", "identical SVG, input order kept",
                         "identical SVG, IDs sorted first"], rows))

    if c:
        refused = sum(r["status"] == "refused" for r in c)
        md.append("## 8. Invalid inputs (tier c)\n")
        md.append(f"{refused} of {len(c)} invalid inputs were refused before drawing.\n")

    (OUT / "summary.md").write_text("\n".join(md))

    html = ["<!doctype html><meta charset='utf-8'><title>e1 layout matrix</title>",
            "<style>body{font-family:sans-serif;margin:16px}figure{margin:0 0 28px}"
            "img{max-width:100%;border:1px solid #ccc}figcaption{font-size:13px;color:#444}"
            "h2{margin-top:36px;border-top:1px solid #ccc;padding-top:10px}</style>",
            "<h1>e1 layout matrix: baseline, best with wires, best overall</h1>",
            "<p>Scores are hard violations / data crossings / crossings / bends / length.</p>"]
    for seed, rs in gallery:
        html.append(f"<h2>{escape(seed)}</h2>")
        seen = set()
        for label, r in rs:
            if r is None or r["combo"] in seen:
                continue
            seen.add(r["combo"])
            s = " / ".join(str(v) for v in score(r))
            html.append(f"<figure><img src='svg/{escape(seed)}/{escape(r['combo'])}.svg'>"
                        f"<figcaption>{label}: <code>{escape(r['combo'])}</code> &nbsp; {s}"
                        f" &nbsp; {r['width']}x{r['height']} px</figcaption></figure>")
    (OUT / "index.html").write_text("\n".join(html))
    print(f"wrote {OUT / 'summary.md'} and {OUT / 'index.html'}")


if __name__ == "__main__":
    main()
