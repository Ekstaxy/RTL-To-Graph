"""Quick Graphviz preview of a Stage 1 view (anchors, groups, anchor arrows).

This is a validation aid for judging "too detailed / too sparse" by eye, not the Stage 3 layout.
"""

from __future__ import annotations

import html
import shutil
import subprocess
from pathlib import Path

from .frontend.graph import DesignGraph
from .trace import Region, anchor_seeds

ROLE_COLOR = {
    "FSM_STATE": "#f4a261",
    "CONTROL_FLAG": "#e9c46a",
    "ENABLE": "#e9c46a",
    "MUX_SELECT": "#e9c46a",
    "COUNTER": "#a8dadc",
    "STATUS": "#e9c46a",
    "COMMAND": "#e9c46a",
    "DECODE": "#e9c46a",
    "HANDSHAKE_VALID": "#90be6d",
    "HANDSHAKE_READY": "#90be6d",
    "INTERFACE_DATA": "#cfe1b9",
    "INTERFACE_ADDR": "#cfe1b9",
    "DATAPATH_MAJOR": "#8ecae6",
    "PIPELINE_REG": "#8ecae6",
    "HOLDING_REG": "#8ecae6",
    "STORAGE": "#bdb2ff",
    "FIFO_PTR": "#bdb2ff",
    "INDEX": "#bdb2ff",
    "CONFIG_REG": "#ffc8dd",
    "ARBITRATION": "#ffafcc",
    "CLOCK_GEN": "#dddddd",
}
EDGE_STYLE = {
    "data": 'color="#1d3557"',
    "control": 'color="#e76f51", style=dashed',
    "addr": 'color="#6a4c93", style=dotted',
}


def to_dot(G: DesignGraph, tables: dict, views: dict, region: Region, title: str = "") -> str:
    seeds = anchor_seeds(G, tables, views)
    top = G.tops[0] if G.tops else ""
    lines = [
        "digraph stage1 {",
        '  rankdir=LR; node [shape=box, style="rounded,filled", fontname="Helvetica", '
        "fontsize=10];",
        '  edge [arrowsize=0.6]; graph [fontname="Helvetica", fontsize=12, labelloc=t, '
        f'label="{html.escape(title)}"];',
    ]
    # group membership: module.id -> group name
    grp: dict[tuple[str, str], str] = {}
    for m, res in views.items():
        for g in res.groups:
            for x in g.anchor_ids:
                grp.setdefault((m, x), f"{m}:{g.name}:{g.kind.value}")
    clusters: dict[str, list[str]] = {}
    loose: list[str] = []
    for k, s in seeds.items():
        n = G.nodes[k]
        where = n.inst[len(top) + 1 :] + "." if n.inst != top else ""
        label = f"{where}{n.name}\\n{s['role']}"
        node = (
            f'  "{k}" [label="{label}", fillcolor="{ROLE_COLOR.get(s["role"], "#ffffff")}", '
            f"penwidth={1 + 2 * s['weight']:.1f}];"
        )
        key = grp.get((s["module"], s["id"]))
        if key:
            clusters.setdefault(f"{n.inst}|{key}", []).append(node)
        else:
            loose.append(node)
    for i, (key, nodes) in enumerate(sorted(clusters.items())):
        inst, gk = key.split("|", 1)
        m, name, kind = gk.split(":")
        where = inst[len(top) + 1 :] + " / " if inst != top else ""
        lines.append(
            f'  subgraph cluster_{i} {{ label="{html.escape(where + name)} ({kind})"; '
            'style=dashed; color="#888888";'
        )
        lines += ["  " + x for x in nodes]
        lines.append("  }")
    lines += loose
    for e in region.anchor_edges:
        lines.append(f'  "{e["src"]}" -> "{e["dst"]}" [{EDGE_STYLE.get(e["kind"], "")}];')
    lines.append("}")
    return "\n".join(lines)


def render(dot: str, out_svg: str | Path) -> Path | None:
    out_svg = Path(out_svg)
    out_svg.parent.mkdir(parents=True, exist_ok=True)
    out_svg.with_suffix(".dot").write_text(dot, encoding="utf-8")
    exe = shutil.which("dot")
    if exe is None:
        return None
    subprocess.run([exe, "-Tsvg", str(out_svg.with_suffix(".dot")), "-o", str(out_svg)], check=True)
    return out_svg
