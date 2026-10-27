"""FSM extraction sanity sweep over manifests (no API).

Checks per extracted FSM: transitions found, every destination is a known state, reset state found,
all states reachable from reset, no extraction warnings.
usage: python experiments/e4_fsm_semantic/check_fsm.py <manifest> ...
"""

import json
import sys
from pathlib import Path

from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate
from rtl2d_l1.frontend.fsm import extract_fsms

tot = ok = 0
problems = []
mealy = []
for m in sys.argv[1:]:
    base = Path(m).parent
    for it in json.loads(Path(m).read_text(encoding="utf-8")):
        files = [str(base / f) for f in it["files"]]
        d = elaborate(files, top=it.get("top"))
        G = build_graph(d)
        for f in extract_fsms(d, G, build_entity_tables(G)):
            tot += 1
            names = {s["name"] for s in f.states}
            issues = list(f.warnings)
            if not f.transitions:
                issues.append("no transitions")
            bad = {t.dst for t in f.transitions if t.dst not in names}
            if bad:
                issues.append(f"unknown dst {bad}")
            if not f.reset_state:
                issues.append("no reset state")
            else:
                reach, frontier = {f.reset_state}, [f.reset_state]
                while frontier:
                    s = frontier.pop()
                    for t in f.transitions:
                        if (t.src == s or t.src == "*") and t.dst not in reach:
                            reach.add(t.dst)
                            frontier.append(t.dst)
                unreach = names - reach
                if unreach:
                    issues.append(f"unreachable {sorted(unreach)}")
            if any(o["kind"] == "mealy" for o in f.outputs):
                mealy.append(f"{it['name']}.{f.state}")
            if issues:
                problems.append(
                    (it["name"], f.module, f.state, len(f.states), len(f.transitions), issues)
                )
            else:
                ok += 1
print(f"FSMs extracted: {tot}, clean: {ok}")
print("with Mealy outputs:", mealy)
for p in problems:
    print("ISSUE", p)
