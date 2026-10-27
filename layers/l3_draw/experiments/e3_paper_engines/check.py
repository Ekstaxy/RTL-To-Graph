"""Round trip for paper drawings: parse the SVG back and compare with the Diagram.

Every block of the Diagram must be drawn; every (net, sink) between two different drawn
items must be listed by exactly one edge whose ends are those two items; every boundary
port that is not clock / reset must sit in a drawn terminal.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from grammar import GLOBAL, PGraph
from p3lib import spec


def roundtrip(g: PGraph, d: spec.Diagram, svg: str) -> list[str]:
    root = ET.fromstring(svg)
    blocks, ports, edges = set(), set(), []
    for el in root.iter():
        k, rid = el.get("data-rtl2d-kind"), el.get("data-rtl2d-id")
        if k == "block":
            blocks.add(rid)
        elif k == "port":
            ports.add(rid)
        elif k == "edge":
            raw = (el.get("data-rtl2d-members") or "").split(";")
            mem = [tuple(x.split("|")) for x in raw if x]
            edges.append((el.get("data-rtl2d-a"), el.get("data-rtl2d-b"), mem))
    issues = []
    want = {b.id for b in d.blocks}
    if blocks != want:
        issues.append(f"blocks differ: missing {sorted(want - blocks)[:3]} "
                      f"extra {sorted(blocks - want)[:3]}")
    owner = {p.id: p.owner_block_id for p in d.ports}
    pin_of = {q: n.id for n in g.nodes.values() if n.kind == "pin" for q in n.ports}
    for p in d.ports:
        if p.owner_block_id is None and (p.class_ or "").lower() not in GLOBAL:
            if pin_of.get(p.id) not in ports:
                issues.append(f"boundary port {p.id} not drawn")
    seen: dict[tuple[str, str], tuple[str, str]] = {}
    for a, b, mem in edges:
        for m in mem:
            if m in seen:
                issues.append(f"{m} drawn twice")
            seen[m] = (a, b)
    for net in d.nets:
        if (net.class_ or "").lower() in GLOBAL:
            continue
        u = owner.get(net.source) or pin_of.get(net.source)
        for t in net.targets:
            v = owner.get(t) or pin_of.get(t)
            if not u or not v or u == v:
                continue
            ends = seen.get((net.id, t))
            if ends is None:
                issues.append(f"{net.id} -> {t} not drawn")
            elif set(ends) != {u, v}:
                issues.append(f"{net.id} -> {t} drawn between {ends}")
    return issues
