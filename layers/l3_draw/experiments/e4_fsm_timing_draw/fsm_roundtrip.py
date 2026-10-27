"""G4 round trip for FSM drawings: every state and transition of the FsmGraph appears exactly
once in the SVG as data-rtl2d-kind="state|transition" data-rtl2d-id=<id>, each transition
element names the same src/dst states as the graph, every transition end is a state of the
graph, and no Graphviz node or edge <g> is left untagged (a dangling end would otherwise
show up as an untagged phantom node).

    uv run --package rtl2d-l3 python \
        layers/l3_draw/experiments/e4_fsm_timing_draw/fsm_roundtrip.py FSM.json FSM.svg
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def tags(svg_text: str) -> list[tuple[str, str, ET.Element]]:
    """(kind, id, element) for every element carrying data-rtl2d-kind and data-rtl2d-id."""
    root = ET.fromstring(svg_text)
    return [(el.get("data-rtl2d-kind"), el.get("data-rtl2d-id"), el) for el in root.iter()
            if el.get("data-rtl2d-kind") and el.get("data-rtl2d-id") is not None]


def _untagged(svg_text: str) -> list[str]:
    """Graphviz node / edge groups without data-rtl2d-kind (by their <title> text)."""
    ns = "{http://www.w3.org/2000/svg}"
    out = []
    for el in ET.fromstring(svg_text).iter(f"{ns}g"):
        if el.get("class") in ("node", "edge") and not el.get("data-rtl2d-kind"):
            title = el.find(f"{ns}title")
            out.append(f"{el.get('class')} {title.text if title is not None else el.get('id')}")
    return out


def check(g: dict, svg_text: str) -> dict:
    """{ok, missing[], extra[], duplicated[], wrong_ends[], untagged[], states, transitions};
    ids in missing/extra are prefixed with their kind ("state:s.IDLE", "transition:t.3")."""
    want = Counter({f"state:{s['id']}": 1 for s in g["states"]})
    want.update({f"transition:{t['id']}": 1 for t in g["transitions"]})
    got: Counter = Counter()
    wrong = []
    trs = {t["id"]: t for t in g["transitions"]}
    sids = {s["id"] for s in g["states"]}
    for t in g["transitions"]:
        for end in ("src", "dst"):
            if t[end] not in sids:
                wrong.append(f"{t['id']}: {end} {t[end]!r} is not a state of the graph")
    for kind, rid, el in tags(svg_text):
        if kind not in ("state", "transition"):
            continue
        got[f"{kind}:{rid}"] += 1
        t = trs.get(rid) if kind == "transition" else None
        if t and (el.get("data-rtl2d-src"), el.get("data-rtl2d-dst")) != (t["src"], t["dst"]):
            wrong.append(f"{rid}: drawn {el.get('data-rtl2d-src')}->{el.get('data-rtl2d-dst')}"
                         f" expected {t['src']}->{t['dst']}")
    untagged = _untagged(svg_text)
    missing = sorted(k for k in want if k not in got)
    extra = sorted(k for k in got if k not in want)
    dup = sorted(k for k, n in got.items() if n > 1)
    return {"ok": not (missing or extra or dup or wrong or untagged), "missing": missing,
            "extra": extra, "duplicated": dup, "wrong_ends": wrong, "untagged": untagged,
            "states": sum(1 for k in got if k.startswith("state:")),
            "transitions": sum(1 for k in got if k.startswith("transition:"))}


def main(argv: list[str]) -> int:
    g = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    r = check(g, Path(argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(r, indent=1))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
