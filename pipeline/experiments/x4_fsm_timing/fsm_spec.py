"""FsmGraph v0.1: the experiment-local L2 -> L3 format for FSM diagrams.

NOT the contract. It lives here, like e0's Diagram v0.1 did, until ADR gate B (plan §5 M6)
proposes it for `contracts/`. Unknown fields are rejected so drift shows up as an error.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "fsm-0.1"

Encoding = Literal["binary", "onehot", "gray", "enum", "other"]
GuardKind = Literal["expr", "cube", "cycles", "unknown", "always"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SrcLine(_M):
    file: str
    line: int


class State(_M):
    id: str  # "s.<name>" ; unique within the graph
    name: str  # RTL name (enum / parameter / localparam) or S_<value> when unnamed
    value: int | None = None  # encoded value of the state register, when known
    reset: bool = False
    reached: bool = True  # reached by execution from reset (semantic engine)
    unnamed: bool = False


class Transition(_M):
    id: str  # "t.<n>"
    src: str  # State.id
    dst: str  # State.id
    guard: str  # "1" for unconditional
    guard_kind: GuardKind
    lines: list[SrcLine] = Field(default_factory=list)
    # where the edge was seen: syntactic (RTL text), semantic (executed), both, yosys, proof
    seen_by: list[str] = Field(default_factory=list)


class Output(_M):
    signal: str
    kind: str  # moore | mealy
    port: bool = False


class Simplification(_M):
    what: str
    reason: str
    lines: list[SrcLine] = Field(default_factory=list)


class Provenance(_M):
    engine: str = "l1-hybrid"  # l1-hybrid | e8-counter
    style: str | None = None  # one-process | two-process | semantic
    seed: int | None = None
    time_budget: float | None = None
    budget_exhausted: bool | None = None
    tool_versions: dict[str, str | None] = Field(default_factory=dict)


class Checks(_M):
    # G1 agree | disagree | yosys_declined | yosys_unparsed | skipped
    yosys: dict = Field(default_factory=dict)
    structural: dict = Field(default_factory=dict)  # G2 {ok, issues[]}
    semantic: dict = Field(default_factory=dict)  # G3 {semantic_check, ok}
    # G6 {status: proven|bounded|failed(edge)|failed(unconstrained)|skipped(...), depth, ...}
    completeness: dict = Field(default_factory=dict)
    roundtrip: dict = Field(default_factory=dict)  # G4 {ok, missing[], extra[]}
    isomorphic: dict = Field(default_factory=dict)  # G5 (filled across rewrites)


class FsmGraph(_M):
    schema_version: Literal["fsm-0.1"] = SCHEMA_VERSION
    design: str
    module: str
    instance: str
    state_reg: str
    width: int | None = None
    encoding: Encoding = "other"
    file: str | None = None
    states: list[State]
    transitions: list[Transition]
    outputs: list[Output] | None = None  # None = not available for this FSM
    simplifications: list[Simplification] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)
    checks: Checks = Field(default_factory=Checks)
    status: Literal["ok", "rejected"] = "ok"
    rejected_reason: str | None = None


def validate(g: FsmGraph) -> list[str]:
    """Checks a schema cannot express. Returns issues; never raises."""
    out: list[str] = []
    ids = [s.id for s in g.states]
    if len(set(ids)) != len(ids):
        out.append("duplicate state id")
    tids = [t.id for t in g.transitions]
    if len(set(tids)) != len(tids):
        out.append("duplicate transition id")
    known = set(ids)
    for t in g.transitions:
        if t.src not in known:
            out.append(f"{t.id}: unknown src {t.src}")
        if t.dst not in known:
            out.append(f"{t.id}: unknown dst {t.dst}")
    if sum(s.reset for s in g.states) > 1:
        out.append("more than one reset state")
    if not any(s.reset for s in g.states):
        out.append("no reset state")
    pairs = [(t.src, t.dst) for t in g.transitions]
    if len(set(pairs)) != len(pairs):
        out.append("more than one transition per (src, dst): merge guards with ||")
    return out
