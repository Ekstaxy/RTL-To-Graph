"""Deterministic validator (SPEC §5)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .frontend.entities import EntityTable
from .schema import ModuleAnnotation
from .taxonomy import LEVEL_ALLOWED_IMPORTANCE, LEVEL_MAX_GROUPS, Direction, Level, Role


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"errors": self.errors, "warnings": self.warnings}


def _source_lines(table: EntityTable) -> dict[int, str]:
    try:
        text = Path(table.file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    return {i: text[i - 1] for i in range(table.line_start, min(table.line_end, len(text)) + 1)}


def check_evidence(ann: ModuleAnnotation, table: EntityTable) -> list[str]:
    """Deterministic anti-hallucination check: every anchor cites RTL lines that mention it."""
    src = _source_lines(table)
    if not src:
        return []
    rows = table.by_id()
    errs = []
    for a in ann.anchors:
        r = rows.get(a.id)
        if r is None:
            continue
        if not a.lines:
            errs.append(f"E_EVIDENCE: {a.id} ({r.name}) cites no RTL lines")
            continue
        base = r.name.split(".")[-1].replace("[*]", "")
        pat = re.compile(r"(?<![\w$])" + re.escape(base) + r"(?![\w$])")
        out_of_range = [n for n in a.lines if n not in src]
        if out_of_range:
            errs.append(
                f"E_EVIDENCE: {a.id} ({r.name}) cites lines {out_of_range} outside the module "
                f"({table.line_start}-{table.line_end})"
            )
        elif not any(pat.search(src[n]) for n in a.lines):
            errs.append(
                f"E_EVIDENCE: {a.id} ({r.name}) is not mentioned on any cited line {a.lines}"
            )
    return errs


def validate(
    ann: ModuleAnnotation,
    table: EntityTable,
    level: Level = Level.MEDIUM,
    require_evidence: bool = False,
) -> Report:
    rep = Report()
    rows = table.by_id()
    seen: set[str] = set()
    for a in ann.anchors:
        r = rows.get(a.id)
        if r is None:
            rep.errors.append(f"E_UNKNOWN_ID: anchor {a.id} ({a.name}) is not in the entity table")
            continue
        if r.name != a.name:
            rep.errors.append(f"E_NAME_MISMATCH: {a.id} is '{r.name}', not '{a.name}'")
        if r.kind == "inst":
            rep.errors.append(
                f"E_UNKNOWN_ID: {a.id} is a sub-instance; "
                "instances may only appear in group member_ids"
            )
        if r.auto_role:
            rep.errors.append(
                f"E_AUTO_ROLE: {a.id} ({r.name}) is a {r.auto_role} net and cannot be an anchor"
            )
        if a.id in seen:
            rep.errors.append(f"E_DUP: {a.id} listed twice in anchors")
        seen.add(a.id)
        # a wire driven by a sub-instance output may legitimately stand for the child's register
        from_child = "inst_out" in r.driven_by
        if a.role == Role.FSM_STATE and not r.is_state and not from_child:
            rep.warnings.append(
                f"W_FSM_NOT_STATE: {a.id} ({r.name}) is not a register; "
                "select the state register instead"
            )
        if a.role == Role.STORAGE and r.kind != "mem" and not r.is_state and not from_child:
            rep.warnings.append(
                f"W_STORAGE_SHAPE: {a.id} ({r.name}) is combinational; STORAGE must hold state"
            )
        if r.fanout == 0 and not r.kind.startswith("port_out"):
            rep.warnings.append(f"W_DEAD: {a.id} ({r.name}) drives nothing")
        if a.importance not in LEVEL_ALLOWED_IMPORTANCE[level]:
            rep.warnings.append(
                f"W_LEVEL: {a.id} has importance {a.importance.value}, "
                f"not allowed at level {level.value}"
            )
    anchor_ids = {a.id for a in ann.anchors}
    for g in ann.groups:
        for x in g.anchor_ids:
            if x not in anchor_ids:
                rep.errors.append(
                    f"E_GROUP_REF: group '{g.name}' anchor_ids has {x}, which is not an anchor"
                )
        for x in g.member_ids:
            if x not in rows:
                rep.errors.append(
                    f"E_UNKNOWN_ID: group '{g.name}' member {x} is not in the entity table"
                )
    if len(ann.groups) > LEVEL_MAX_GROUPS[level]:
        rep.warnings.append(
            f"W_LEVEL: {len(ann.groups)} groups exceeds {LEVEL_MAX_GROUPS[level]} "
            f"for level {level.value}"
        )
    for itf in ann.interfaces:
        dirs = []
        for x in itf.member_ids:
            r = rows.get(x)
            if r is None:
                rep.errors.append(
                    f"E_UNKNOWN_ID: interface '{itf.name}' member {x} is not in the entity table"
                )
            elif r.kind.startswith("port_"):
                dirs.append(r.kind)
        if dirs and itf.direction == Direction.IN and all(d == "port_out" for d in dirs):
            rep.warnings.append(
                f"W_PORT_DIR: interface '{itf.name}' is IN but all members are outputs"
            )
        if dirs and itf.direction == Direction.OUT and all(d == "port_in" for d in dirs):
            rep.warnings.append(
                f"W_PORT_DIR: interface '{itf.name}' is OUT but all members are inputs"
            )
    if require_evidence or any(a.lines for a in ann.anchors):
        rep.errors += check_evidence(ann, table)
    for r in table.rows:
        if r.fsm_candidate and r.id not in anchor_ids:
            rep.warnings.append(
                f"W_MISSED_FSM: {r.id} ({r.name}) looks like an FSM state register "
                "but was not selected"
            )
    return rep
