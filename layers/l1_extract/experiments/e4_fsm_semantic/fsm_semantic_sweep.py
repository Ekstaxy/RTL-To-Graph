"""Semantic FSM detection over corpora: syntactic vs semantic agreement, semantic-only finds."""

import json
import sys
import time
from pathlib import Path

from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate
from rtl2d_l1.frontend.fsm_semantic import detect, state_graph

tot = {"designs": 0, "syn": 0, "sem": 0, "both": 0, "syn_only": [], "sem_only": [], "errors": []}
t0 = time.time()
for m in sys.argv[1:]:
    base = Path(m).parent
    for it in json.loads(Path(m).read_text(encoding="utf-8")):
        files = [str(base / f) for f in it["files"]]
        d = elaborate(
            files,
            top=it.get("top"),
            include_dirs=[str(base / i) for i in it.get("include_dirs", [])],
        )
        G = build_graph(d)
        T = build_entity_tables(G)
        syn = {
            k
            for t in T
            for r in t.rows
            if r.fsm_candidate
            for k in ([*r.members] if r.members else [f"{t.canonical_instance}.{r.name}"])
        }
        t1 = time.time()
        sem = detect(d, G, syn, samples_per_state=150, time_budget=30)
        print(
            f"  {it['name']}: {len(syn)} syntactic, "
            f"{sum(1 for r in sem if not r.error)} semantic, {time.time() - t1:.1f}s",
            flush=True,
        )
        ok = {r.state for r in sem if not r.error}
        tot["designs"] += 1
        tot["syn"] += len(syn)
        tot["sem"] += len(ok)
        tot["both"] += len(syn & ok)
        tot["syn_only"] += [
            f"{it['name']}:{k} ({next((r.error for r in sem if r.state == k), 'not reached')})"
            for k in syn - ok
        ]
        for r in sem:
            if r.state in ok - syn:
                tot["sem_only"].append(
                    f"{it['name']}:{r.state} w={G.nodes[r.state].width} "
                    f"states={len(r.states)} edges={state_graph(r).number_of_edges()}"
                )
print(
    json.dumps({k: v for k, v in tot.items() if not isinstance(v, list)}, indent=1),
    f"{time.time() - t0:.0f}s",
)
print("syntactic candidates the semantic engine could not analyze:")
for x in tot["syn_only"]:
    print("  ", x)
print("semantic-only FSMs:")
for x in tot["sem_only"]:
    print("  ", x)
