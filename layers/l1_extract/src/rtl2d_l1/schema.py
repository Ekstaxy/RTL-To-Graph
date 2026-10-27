"""Data contracts (SPEC §3, §4). Pydantic models + the JSON schema sent to the teacher."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .taxonomy import Direction, GroupKind, Importance, Level, Protocol, Role, TraceHint
from .versions import ENTITIES_VERSION, TAXONOMY_VERSION

EntityKind = Literal[
    "port_in", "port_out", "port_inout", "reg", "latch", "comb", "wire", "mem", "local", "inst"
]


class EntityRow(BaseModel):
    id: str
    name: str
    kind: EntityKind
    width: int = 0
    depth: int | None = None
    type_str: str = ""
    enum_values: list[str] = Field(default_factory=list)
    driven_by: list[str] = Field(default_factory=list)
    fanin: int = 0
    fanout: int = 0
    ctrl_fanout: int = 0
    addr_fanout: int = 0
    is_state: bool = False
    fsm_candidate: bool = False
    auto_role: Literal["CLOCK", "RESET"] | None = None
    name_hints: list[str] = Field(default_factory=list)
    line: int = 0
    definition: str | None = None
    members: list[str] = Field(default_factory=list)


class EntityTableModel(BaseModel):
    version: str = ENTITIES_VERSION
    design: str
    module: str
    canonical_instance: str
    file: str
    line_start: int
    line_end: int
    rows: list[EntityRow]


# ----------------------------------------------------------------- annotation
class Anchor(BaseModel):
    id: str
    name: str
    role: Role
    importance: Importance
    trace: TraceHint
    why: str = ""
    lines: list[int] = Field(default_factory=list)  # RTL evidence lines (absolute line numbers)


class Group(BaseModel):
    name: str
    kind: GroupKind
    anchor_ids: list[str]
    member_ids: list[str] = Field(default_factory=list)
    description: str = ""


class Interface(BaseModel):
    name: str
    protocol: Protocol
    direction: Direction
    member_ids: list[str]


class ModuleAnnotation(BaseModel):
    module_summary: str = ""
    anchors: list[Anchor] = Field(default_factory=list)
    groups: list[Group] = Field(default_factory=list)
    interfaces: list[Interface] = Field(default_factory=list)


class VotedAnchor(Anchor):
    confidence: float = 1.0
    score: float | None = None  # 0-100 quantified importance (importance.py, SPEC §4.6)
    struct_score: float | None = None  # same scale, structure + role only (ignores the tier)


class ModuleResult(BaseModel):
    """Final per-module result written to anchors.json (SPEC appendix)."""

    module: str
    canonical_instance: str
    source: Literal["teacher", "heuristic", "student", "human"]
    level: Level = Level.MEDIUM
    module_summary: str = ""
    anchors: list[VotedAnchor] = Field(default_factory=list)
    groups: list[Group] = Field(default_factory=list)
    interfaces: list[Interface] = Field(default_factory=list)
    run_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnchorsFile(BaseModel):
    schema_version: str = "anchors-v1"
    taxonomy_version: str = TAXONOMY_VERSION
    design: str
    tops: list[str]
    modules: dict[str, ModuleResult]


# -------------------------------------------------------- teacher JSON schema
def _enum(e) -> list[str]:
    return [m.value for m in e]


def annotation_json_schema() -> dict:
    """Hand-written strict schema for structured outputs (no numeric bounds, all required)."""
    s = lambda: {"type": "string"}  # noqa: E731
    ids = {"type": "array", "items": {"type": "string"}}
    anchor = {
        "type": "object",
        "properties": {
            "id": s(),
            "name": s(),
            "role": {"type": "string", "enum": _enum(Role)},
            "importance": {"type": "string", "enum": _enum(Importance)},
            "trace": {"type": "string", "enum": _enum(TraceHint)},
            "why": s(),
            "lines": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["id", "name", "role", "importance", "trace", "why", "lines"],
        "additionalProperties": False,
    }
    group = {
        "type": "object",
        "properties": {
            "name": s(),
            "kind": {"type": "string", "enum": _enum(GroupKind)},
            "anchor_ids": ids,
            "member_ids": ids,
            "description": s(),
        },
        "required": ["name", "kind", "anchor_ids", "member_ids", "description"],
        "additionalProperties": False,
    }
    iface = {
        "type": "object",
        "properties": {
            "name": s(),
            "protocol": {"type": "string", "enum": _enum(Protocol)},
            "direction": {"type": "string", "enum": _enum(Direction)},
            "member_ids": ids,
        },
        "required": ["name", "protocol", "direction", "member_ids"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "module_summary": s(),
            "anchors": {"type": "array", "items": anchor},
            "groups": {"type": "array", "items": group},
            "interfaces": {"type": "array", "items": iface},
        },
        "required": ["module_summary", "anchors", "groups", "interfaces"],
        "additionalProperties": False,
    }
