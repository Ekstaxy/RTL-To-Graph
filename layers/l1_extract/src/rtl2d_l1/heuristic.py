"""Heuristic baseline annotator (SPEC §10: must always be reported next to the teacher).

Uses only name hints + structural features from the entity table. It is also the
labeler for trivial modules that are not worth an API call (SPEC §7.1).
"""

from __future__ import annotations

import re
from collections import defaultdict

from .frontend.entities import EntityTable
from .schema import Anchor, EntityRow, Group, Interface, ModuleAnnotation
from .taxonomy import (
    LEVEL_ALLOWED_IMPORTANCE,
    Direction,
    GroupKind,
    Importance,
    Level,
    Protocol,
    Role,
    TraceHint,
)


def _prefix(name: str) -> str:
    parts = re.split(r"_", name.lower())
    return parts[0] if len(parts) > 1 else "__single__"


def port_bundles(table: EntityTable) -> list[Interface]:
    ports = [r for r in table.rows if r.kind.startswith("port_")]
    by_pref: dict[str, list[EntityRow]] = defaultdict(list)
    for r in ports:
        if r.auto_role:
            by_pref["clock_reset"].append(r)
        else:
            by_pref[_prefix(r.name)].append(r)
    out = []
    for pref, rs in by_pref.items():
        hints = set().union(*(set(r.name_hints) for r in rs))
        if pref == "clock_reset":
            proto, name = Protocol.CLOCK_RESET, "clock_reset"
        elif "valid" in hints and "ready" in hints:
            proto, name = Protocol.VALID_READY, pref
        elif "req" in hints and ("ack" in hints or "grant" in hints):
            proto, name = Protocol.REQ_ACK, pref
        elif "addr" in hints and "data" in hints:
            proto, name = Protocol.MEMORY_BUS, pref
        elif "valid" in hints:
            proto, name = Protocol.STREAM, pref
        else:
            proto, name = Protocol.SIMPLE, pref if pref != "__single__" else "misc"
        ins = sum(r.width for r in rs if r.kind == "port_in")
        outs = sum(r.width for r in rs if r.kind == "port_out")
        d = Direction.IN if ins > outs else Direction.OUT if outs > ins else Direction.BIDIR
        out.append(Interface(name=name, protocol=proto, direction=d, member_ids=[r.id for r in rs]))
    return out


def heuristic_annotation(table: EntityTable, level: Level = Level.MEDIUM) -> ModuleAnnotation:
    anchors: list[Anchor] = []

    def add(r: EntityRow, role: Role, imp: Importance, trace: TraceHint, why: str):
        anchors.append(
            Anchor(id=r.id, name=r.name, role=role, importance=imp, trace=trace, why=why)
        )

    for r in table.rows:
        if r.kind == "inst" or r.auto_role:
            continue
        h = set(r.name_hints)
        is_port = r.kind.startswith("port_")
        if (
            is_port
            and r.kind == "port_out"
            and h & {"busy", "done", "err", "irq"}
            and r.width == 1
            and not h & {"valid"}
        ):
            add(r, Role.STATUS, Importance.major, TraceHint.control_backward, "status output")
        elif (
            is_port
            and r.kind == "port_in"
            and r.width <= 4
            and re.search(r"start|(^|_)(rw|op|mode|cmd|flush)", r.name, re.I)
        ):
            add(r, Role.COMMAND, Importance.major, TraceHint.forward, "command input")
        elif r.fsm_candidate:
            add(r, Role.FSM_STATE, Importance.critical, TraceHint.control_backward, "fsm candidate")
        elif r.kind == "mem":
            add(r, Role.STORAGE, Importance.major, TraceHint.data_backward, "memory array")
        elif is_port and "valid" in h:
            add(r, Role.HANDSHAKE_VALID, Importance.critical, TraceHint.interface, "valid port")
        elif is_port and ("ready" in h or "ack" in h or "grant" in h):
            add(r, Role.HANDSHAKE_READY, Importance.critical, TraceHint.interface, "ready/ack port")
        elif is_port and "req" in h and r.width == 1:
            add(r, Role.HANDSHAKE_VALID, Importance.critical, TraceHint.interface, "req port")
        elif r.is_state and "ptr" in h:
            add(r, Role.FIFO_PTR, Importance.major, TraceHint.control_backward, "pointer register")
        elif r.is_state and "cnt" in h:
            add(r, Role.COUNTER, Importance.major, TraceHint.control_backward, "counter register")
        elif r.is_state and r.ctrl_fanout >= 3:
            add(
                r,
                Role.CONTROL_FLAG,
                Importance.major,
                TraceHint.control_backward,
                "register with high control fanout",
            )
        elif not is_port and r.ctrl_fanout >= 3 and r.width == 1:
            add(r, Role.CONTROL_FLAG, Importance.minor, TraceHint.control_backward, "control net")
        elif is_port and "addr" in h:
            add(r, Role.INTERFACE_ADDR, Importance.minor, TraceHint.interface, "address port")
        elif is_port and r.width >= 8:
            add(r, Role.INTERFACE_DATA, Importance.minor, TraceHint.interface, "wide data port")

    anchors = [a for a in anchors if a.importance in LEVEL_ALLOWED_IMPORTANCE[level]]
    groups: list[Group] = []
    fsm = [a.id for a in anchors if a.role == Role.FSM_STATE]
    if fsm:
        groups.append(
            Group(name="controller", kind=GroupKind.CONTROLLER, anchor_ids=fsm, description="FSM")
        )
    mem = [a.id for a in anchors if a.role in (Role.STORAGE, Role.FIFO_PTR)]
    if mem:
        groups.append(
            Group(name="storage", kind=GroupKind.BUFFER, anchor_ids=mem, description="storage")
        )
    insts = [r.id for r in table.rows if r.kind == "inst"]
    if insts:
        groups.append(
            Group(name="submodules", kind=GroupKind.OTHER, anchor_ids=[], member_ids=insts)
        )
    return ModuleAnnotation(
        module_summary=f"{table.module} (heuristic)",
        anchors=anchors,
        groups=groups,
        interfaces=port_bundles(table),
    )


def is_trivial(table: EntityTable) -> bool:
    """SPEC §7.1: modules not worth an API call."""
    sigs = [r for r in table.rows if r.kind != "inst" and not r.auto_role]
    has_state = any(r.is_state for r in sigs)
    has_children = any(r.kind == "inst" for r in table.rows)
    has_fsm = any(r.fsm_candidate for r in sigs)
    if has_fsm or has_children:
        return False
    return len(sigs) <= 4 or not has_state
