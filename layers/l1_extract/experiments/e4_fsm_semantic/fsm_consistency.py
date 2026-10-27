"""Cross-check: syntactic FSM transition graph vs executed (semantic) graph, per FSM."""

import collections
import json
import sys
from pathlib import Path

from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate
from rtl2d_l1.frontend.fsm_hybrid import extract_fsms_hybrid

c = collections.Counter()
bad = []
for m in sys.argv[1:]:
    base = Path(m).parent
    for it in json.loads(Path(m).read_text(encoding="utf-8")):
        d = elaborate(
            [str(base / f) for f in it["files"]],
            top=it.get("top"),
            include_dirs=[str(base / i) for i in it.get("include_dirs", [])],
        )
        G = build_graph(d)
        T = build_entity_tables(G)
        if not any(r.fsm_candidate for t in T for r in t.rows):
            continue
        for f in extract_fsms_hybrid(d, G, T):
            st = getattr(f, "semantic_check", None)
            c[st] += 1
            if st in ("mismatch", "unsupported"):
                bad.append(
                    (it["name"], f.state, st, [w for w in f.warnings if "semantic" in w][:1])
                )
print(dict(c))
for b in bad:
    print("  ", b)
