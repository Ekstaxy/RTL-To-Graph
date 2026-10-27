"""x1 bridge output (L1 -> e0 diagram + meta) -> e3 paper-figure input (diagram + sidecar).

This is the L2 stand-in's job, done here so that L3 stays untouched:
1. wiring helpers the bridge made (`split` / `join` blocks: bus fields, multi-driver
   merges) are collapsed into direct connections between real units;
2. a teacher group with several members becomes a titled container (`parent_id`); a group
   with one instance names that instance ("CPU", "UART");
3. hubs (teacher ARBITER / DECODER groups, or names like crossbar, interconnect, bus,
   decode, demux, switch, arbiter) get `role: bus` so e3 draws them as bars;
4. `count` from generate-array folding (ADR-0003) becomes `replicate`;
5. the teacher's boundary interfaces (ADR-0003 `interfaces`) group terminals.

Collapsing step 1 gives nets that ADR-0002 v0.1 does not allow (a port driven by several
nets after a join is removed; endpoints of different widths after a split). The adapted
diagram is therefore checked with v0.1 rules 1-7 only; rules 8 (width) and 9 (one net per
port) are reported, not enforced. The bridge's own diagram is checked with all rules.
"""

from __future__ import annotations

import re
from collections import defaultdict

HUB = re.compile(r"crossbar|interconnect|xbar|\bbus\b|decode|demux|switch|arbiter|\bnoc\b|"
                 r"router", re.I)
KIND_OF_GROUP = {"CONTROLLER": "controller", "ARBITER": "bus", "DECODER": "bus",
                 "MEMORY": "memory", "BUFFER": "fifo", "REGISTER_BANK": "regfile",
                 "INTERFACE_ADAPTER": "peripheral", "SERIALIZER": "peripheral",
                 "DATAPATH": "comb", "PIPELINE_STAGE": "register", "COUNTER_TIMER": "register"}
CPU = re.compile(r"\b(cpu|core|risc|processor|hart)\b", re.I)


def adapt(diagram: dict, meta: dict) -> tuple[dict, dict, list[str]]:
    kinds = meta["kinds"]
    notes: list[str] = []
    wiring = {b["id"] for b in diagram["blocks"] if kinds.get(b["id"]) == "split"}
    owner = {p["id"]: p["owner_block_id"] for p in diagram["ports"]}
    out_of = defaultdict(list)
    for n in diagram["nets"]:
        if owner[n["source"]] in wiring:
            out_of[owner[n["source"]]].append(n)

    def resolve(n: dict, depth: int = 0) -> list[str]:
        res = []
        for t in n["targets"]:
            ob = owner[t]
            if ob in wiring and depth < 8:
                for n2 in out_of.get(ob, []):
                    res += resolve(n2, depth + 1)
            else:
                res.append(t)
        return res

    nets = []
    for n in diagram["nets"]:
        if owner[n["source"]] in wiring:
            continue
        ts = list(dict.fromkeys(resolve(n)))
        if ts:
            nets.append({**n, "targets": ts})
    used = {p for n in nets for p in (n["source"], *n["targets"])}
    ports = [p for p in diagram["ports"] if owner[p["id"]] not in wiring
             and (p["id"] in used or p["owner_block_id"] is None)]
    blocks = [dict(b) for b in diagram["blocks"] if b["id"] not in wiring]
    if wiring:
        notes.append(f"collapsed {len(wiring)} wiring blocks")
    ids = {b["id"] for b in blocks}
    by = {b["id"]: b for b in blocks}
    side_nodes: dict[str, dict] = {}

    # teacher groups -> containers or names
    used_in_group: set[str] = set()
    merged: dict[str, str] = {}  # glue-logic block -> the instance it is drawn as
    for g in meta.get("teacher_groups", []):
        inst = [b for b in g["instances"] if b in ids and b not in used_in_group]
        logic = g.get("logic") if g.get("logic") in ids else None
        if len(inst) == 1 and logic and logic not in used_in_group:
            # one instance plus its glue: one box named by the group (x1 RULES S2)
            merged[logic] = inst[0]
            used_in_group.add(logic)
        members = [b for b in [*inst, logic] if b and b not in merged and b in ids
                   and b not in used_in_group]
        if not members:
            continue
        kind = KIND_OF_GROUP.get(g["kind"], "comb")
        if CPU.search(g["name"]):
            kind = "cpu"
        if len(members) == 1:
            b = by[members[0]]
            b["label"], b["kind"] = g["name"], kind
            used_in_group.add(b["id"])
            if g["kind"] in ("ARBITER", "DECODER") or HUB.search(g["name"]):
                side_nodes.setdefault(b["id"], {})["role"] = "bus"
            continue
        cid = re.sub(r"[^A-Za-z0-9_.\-]", "_", "c." + g["name"])
        while cid in ids:
            cid += "_"
        blocks.append({"id": cid, "label": g["name"], "kind": "group", "parent_id": None})
        ids.add(cid)
        for m in members:
            by[m]["parent_id"] = cid
            used_in_group.add(m)
        notes.append(f"container {g['name']!r} with {len(members)} units")
    for b in blocks:
        if b["id"] in side_nodes or b["kind"] == "group":
            continue
        if HUB.search(b["label"] or ""):
            side_nodes.setdefault(b["id"], {})["role"] = "bus"
        if b.get("kind") in kinds.values() and b["id"] not in used_in_group:
            b["kind"] = {"control": "controller", "split": "comb"}.get(b["kind"], b["kind"])
        if CPU.search(b["label"] or ""):
            b["kind"] = "cpu"
    if merged:
        for p in ports:
            if p["owner_block_id"] in merged:
                p["owner_block_id"] = merged[p["owner_block_id"]]
        blocks = [b for b in blocks if b["id"] not in merged]
        ids -= set(merged)
        notes.append(f"merged glue logic of {len(merged)} groups into their instance")
    for bid, c in (meta.get("count") or {}).items():
        if bid in ids and c > 1:
            side_nodes.setdefault(bid, {})["replicate"] = {"count": c, "shape": "stack"}
            if " ×" in by[bid]["label"]:
                by[bid]["label"] = by[bid]["label"].split(" ×")[0]
    pin_groups = {p: i["name"] for i in meta.get("interfaces", []) for p in i["ports"]
                  if i["protocol"] != "CLOCK_RESET"}
    side = {"nodes": side_nodes, "arrays": [], "expected": {}, "aspect": 1.78,
            "pin_groups": pin_groups}
    new = {"schema_version": diagram["schema_version"], "blocks": blocks, "ports": ports,
           "nets": nets}
    return new, side, notes


def check(d: dict) -> tuple[list[str], list[str]]:
    """(errors, relaxed): v0.1 rules 1-7 are errors; width / single-driver are relaxed."""
    errs, relaxed = [], []
    ids = ([b["id"] for b in d["blocks"]] + [p["id"] for p in d["ports"]]
           + [n["id"] for n in d["nets"]])
    if len(ids) != len(set(ids)):
        errs.append("duplicate ids")
    bid = {b["id"] for b in d["blocks"]}
    port = {p["id"]: p for p in d["ports"]}
    for b in d["blocks"]:
        if b["parent_id"] and b["parent_id"] not in bid:
            errs.append(f"{b['id']}: unknown parent")
    for n in d["nets"]:
        for p in (n["source"], *n["targets"]):
            if p not in port:
                errs.append(f"{n['id']}: unknown port {p}")
        for p in (n["source"], *n["targets"]):
            if p in port and port[p]["width"] != n["width"]:
                relaxed.append(f"{n['id']}: width {n['width']} vs {p} {port[p]['width']}")
    tgt = defaultdict(int)
    for n in d["nets"]:
        for t in n["targets"]:
            tgt[t] += 1
    relaxed += [f"{p}: {c} drivers" for p, c in tgt.items() if c > 1]
    return errs, relaxed
