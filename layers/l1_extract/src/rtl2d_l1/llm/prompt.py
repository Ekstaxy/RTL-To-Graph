"""Teacher/student prompt (identical I/O for both, SPEC §9).

The system prompt is static and byte-stable so it can be prompt-cached. Everything
module-specific goes in the user message.
"""

from __future__ import annotations

import hashlib
import json

from ..frontend.entities import EntityTable
from ..schema import EntityRow, ModuleResult
from ..taxonomy import LEVEL_DEFS, ROLE_DEFS, ROLE_RULES, GroupKind, Level, Protocol

PROMPT_VERSION = "anchor-v2.1"


def _role_block() -> str:
    return "\n".join(f"- {r.value}: {d}" for r, d in ROLE_DEFS.items())


def _rules_block() -> str:
    return "\n".join(f"- {r}" for r in ROLE_RULES)


def _level_block() -> str:
    return "\n".join(f"- {lv.value}: {d}" for lv, d in LEVEL_DEFS.items())


SYSTEM_PROMPT = f"""You are an expert digital-design architect. You read synthesizable Verilog/SystemVerilog and identify the semantic anchors a human would put on a block diagram.

# Your job
For ONE module, select the entities that carry its architecture, assign each a role, group them into latent functional blocks, and describe its port interfaces. A deterministic trace engine will later expand your anchors through the real dependency graph, so:
- Prefer few, precise anchors over many. Do NOT list every intermediate wire; the trace engine recovers connectivity.
- But every functional concept in the module (each controller, each handshake, each storage element, each counter/timer, each major datapath result) must get at least one anchor.
- You never describe connections. You only pick entities.

# Hard rules
1. Use ONLY ids from the ENTITY TABLE. Every anchor must give both `id` and the exact `name` from that row.
2. Never select a row whose flags include CLOCK or RESET.
3. Sub-instances (ids starting with I) may only appear in group `member_ids`, never in `anchors`.
4. Judge by structure, not by names: names can be misleading or obfuscated. Use kind, driven_by, fanout, ctrl_fanout (how many entities this one controls), addr_fanout, STATE and FSM? flags, and the RTL itself.
5. If a state register has a combinational next-state twin (state_q / state_d), anchor only the register.
6. `why` and `description`: at most 20 words, concrete (mention what it controls/stores).
6b. `lines`: 1-3 line numbers from the line-numbered RTL that justify the anchor (where it is assigned, decoded or used in the way its role claims). Every cited line must contain the entity's name; the validator rejects anchors whose evidence does not.
7. `module_summary`: one sentence on what the module does and how (architecture, not just function).

# Roles (taxonomy roles-v2)
{_role_block()}

# Tie-break rules
{_rules_block()}

# Importance
- critical: a block diagram of this module is wrong without it.
- major: belongs on a normal block diagram.
- minor: internal detail useful only for a detailed diagram.

# Trace hint (how the trace engine should expand from this anchor)
- control_backward: follow what decides this signal (FSM, flags, enables).
- data_backward: follow where the data comes from (storage, datapath results).
- forward: follow what this signal affects (events, triggers).
- interface: port-level: connect the port to the first registers inside.
- none: keep the anchor alone.

# Detail and importance
Always annotate at full detail (every functional concept, including minor internal ones).
Users later derive coarser views purely by filtering on importance:
{_level_block()}
So importance must be calibrated: a reader of the HIGH view (critical only) must still see what the module is and how it talks to the outside; MEDIUM (critical + major) is a normal block diagram.

# Groups (latent functional blocks)
Kinds: {", ".join(k.value for k in GroupKind)}.
A group is a hint, not an exact boundary. anchor_ids must be a subset of your anchors; member_ids may add other entity ids or sub-instances (I*) that belong to the block.

# Interfaces
Bundle the ports into protocol groups. Protocols: {", ".join(p.value for p in Protocol)}.
direction is the main data direction seen from this module (IN = this module receives data).
Every port should appear in exactly one interface (clock/reset ports go to a CLOCK_RESET interface).

# Child modules
When CHILD SUMMARIES are given, treat each sub-instance as a black box with the summarized interfaces; anchor the signals in THIS module that connect, select or sequence the children.
"""


def _row_line(r: EntityRow) -> str:
    if r.kind == "inst":
        return f"{r.id} | {r.name} | inst of {r.definition} | fanin={r.fanin} fanout={r.fanout} | L{r.line}"
    size = f"{r.width}b" + (f" x{r.depth}" if r.depth else "")
    flags = []
    if r.is_state:
        flags.append("STATE")
    if r.fsm_candidate:
        flags.append("FSM?")
    if r.auto_role:
        flags.append(r.auto_role)
    typ = r.type_str
    if r.enum_values:
        typ += "{" + ",".join(r.enum_values) + "}"
    return (
        f"{r.id} | {r.name} | {r.kind} | {size} | {typ} | driven_by={','.join(r.driven_by) or '-'} | "
        f"fanin={r.fanin} fanout={r.fanout} ctrl_fanout={r.ctrl_fanout} addr_fanout={r.addr_fanout} | "
        f"{' '.join(flags) or '-'} | L{r.line}"
    )


def render_entity_table(t: EntityTable) -> str:
    head = "id | name | kind | size | type | driven_by | fan | flags | line"
    return head + "\n" + "\n".join(_row_line(r) for r in t.rows)


def render_child_summaries(t: EntityTable, child_results: dict[str, ModuleResult]) -> str:
    lines = []
    for iid, defn in sorted(t.children.items(), key=lambda kv: int(kv[0][1:])):
        res = child_results.get(defn)
        name = t.by_id()[iid].name
        if res is None:
            lines.append(f"{iid} {name}: {defn} (no summary)")
            continue
        lines.append(f"{iid} {name}: {defn} -- {res.module_summary}")
        for itf in res.interfaces:
            lines.append(f"    interface {itf.name}: {itf.protocol.value} {itf.direction.value}")
        crit = [a for a in res.anchors if a.importance.value == "critical"]
        if crit:
            lines.append(
                "    key internals: " + ", ".join(f"{a.name}({a.role.value})" for a in crit)
            )
    return "\n".join(lines)


def user_message(
    t: EntityTable,
    level: Level = Level.MEDIUM,
    child_results: dict[str, ModuleResult] | None = None,
) -> str:
    parts = [
        f"MODULE: {t.module}",
        "DETAIL: full (importance tiers drive the coarser views)",
        "",
        "ENTITY TABLE:",
        render_entity_table(t),
    ]
    if t.children:
        parts += ["", "CHILD SUMMARIES:", render_child_summaries(t, child_results or {})]
    parts += ["", "RTL (line-numbered):", t.source_text(numbered=True)]
    return "\n".join(parts)


def privileged_block(
    spec: str | None, module: str | None = None, tops: list[str] | None = None
) -> str:
    """Teacher-only design spec (never part of the student input or the SFT sample)."""
    if not spec:
        return ""
    scope = ""
    if module and tops and module not in tops:
        scope = (
            f"NOTE: the spec describes the whole design (top: {', '.join(tops)}). This module ({module}) is only "
            "a SUBMODULE of it; use only the parts of the spec this module implements and do not describe the "
            "whole design in module_summary.\n"
        )
    return (
        "\n\nDESIGN SPEC (teacher-only reference; use it to understand intent, but anchors must be grounded "
        "in the RTL and entity table, and the RTL wins if they disagree):\n"
        + scope
        + spec.strip()[:12000]
    )


def unit_hash(user_msg: str, model: str, effort: str) -> str:
    h = hashlib.sha256()
    h.update(PROMPT_VERSION.encode())
    h.update(hashlib.sha256(SYSTEM_PROMPT.encode()).digest())
    h.update(user_msg.encode())
    h.update(model.encode())
    h.update(effort.encode())
    return h.hexdigest()[:20]


def retry_message(errors: list[str]) -> str:
    return (
        "Your annotation failed validation:\n"
        + "\n".join(f"- {e}" for e in errors)
        + "\nReturn the full corrected annotation (same JSON schema)."
    )


def refine_message(findings: list[str]) -> str:
    return (
        "Automatic checks on your annotation (validator + trace engine over the real dependency graph) report:\n"
        + "\n".join(f"- {f}" for f in findings)
        + "\nFor each finding either fix the annotation or keep it if you are confident it is not architecturally relevant. "
        "Return the full final annotation (same JSON schema)."
    )


AUDIT_CHECKLIST = (
    "1. For EVERY anchor: re-read its cited lines. Do they really show this entity doing what the role claims? "
    "Is it the right entity of its concept (register vs. next-state twin vs. port copy, per the tie-break rules)?\n"
    "2. Role: is there a more specific roles-v2 role? Apply the tie-break rules literally.\n"
    "3. Importance: critical only if a block diagram is wrong without it; keep the MEDIUM view (critical+major) "
    "within the size rule; ports are critical only for the primary handshake/data.\n"
    "4. Missing concepts: walk the entity table top to bottom; every STATE register, memory, FSM? row and "
    "high-ctrl_fanout signal must be covered by an anchor or deliberately left as an internal detail.\n"
    "5. Groups and interfaces: every port in exactly one interface; group anchor_ids are anchors.\n"
)


def audit_message(n: int, findings: list[str]) -> str:
    """Pass n >= 2 of the multi-pass protocol: an explicit self-audit against the RTL."""
    if findings:
        f = "Automatic checks report:\n" + "\n".join(f"- {x}" for x in findings) + "\n"
    else:
        f = "Automatic checks report no findings.\n"
    return (
        f"AUDIT PASS {n}. Audit your previous annotation against the RTL with this checklist:\n"
        + AUDIT_CHECKLIST
        + f
        + "Fix every problem you find. If nothing needs to change, return the annotation unchanged. "
        "Return the full annotation (same JSON schema)."
    )


def dump_request_preview(system: str, user: str) -> str:
    return json.dumps({"system": system, "user": user}, ensure_ascii=False, indent=2)
