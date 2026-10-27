"""TimingDiagram v0.1: the experiment-local L2 -> L3 format for timing diagrams.

NOT the contract (see fsm_spec.py). Time is in simulation time units of the generated or
given testbench; every lane value is a sample of the VCD at its own domain's clock posedge.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "timing-0.1"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SrcLine(_M):
    file: str
    line: int


class Sample(_M):
    cycle: int  # posedge index in this lane's domain (0 = first posedge in the VCD)
    t: int  # simulation time of that posedge
    v: str  # "0" | "1" | "x" | "z" | hex string for buses (lower-case, no prefix)


class Lane(_M):
    id: str  # "l.<n>"
    signal: str  # RTL name relative to the module (e.g. "in_valid", "state_q")
    width: int
    role: str  # valid | ready | data | req | ack | addr | we | state | reg | ...
    interface: str | None = None
    values: list[Sample]  # only the drawn cycles (inside windows), in order
    enum: dict[str, str] | None = None  # value -> state name, for FSM state lanes


class Domain(_M):
    id: str  # "d.<clock>"
    clock: str  # clock port name
    period: int  # simulation time units
    phase: int = 0  # time of the first posedge
    lanes: list[Lane]


class Window(_M):
    t0: int
    t1: int  # inclusive
    reason: str  # e.g. "first fire of in (valid && ready)"


class Gap(_M):
    after_t: int  # last drawn time before the gap
    until_t: int  # first drawn time after the gap
    cycles: dict[str, int]  # domain id -> posedges hidden in the gap (exact)


class End(_M):
    lane: str
    cycle: int
    t: int


class Arrow(_M):
    id: str  # "a.<n>"
    src: End
    dst: End
    regs: int  # registers on the path: 0 = same cycle, 1 = next cycle
    kind: Literal["same", "next", "cdc"]
    path: list[str]  # graph node keys from src signal to dst signal
    via_lines: list[SrcLine] = Field(default_factory=list)


class Stimulus(_M):
    kind: Literal["tb", "generated", "cover"]
    tb_path: str
    seed: int | None = None
    simulator: str
    version: str | None = None
    cmd: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    vcd_sha256: str | None = None
    timescale: str | None = None  # unit of every time in this diagram, e.g. "1ps"


class Simplification(_M):
    what: str
    reason: str
    lines: list[SrcLine] = Field(default_factory=list)


class TimingDiagram(_M):
    schema_version: Literal["timing-0.1"] = SCHEMA_VERSION
    id: str  # "<design>.<interface>.<scenario>"
    design: str
    module: str
    interface: str
    protocol: str
    scenario: str  # e.g. "first-fire", "stall", "back-to-back", "fsm"
    stimulus: Stimulus
    domains: list[Domain]
    windows: list[Window]
    gaps: list[Gap] = Field(default_factory=list)
    arrows: list[Arrow] = Field(default_factory=list)
    simplifications: list[Simplification] = Field(default_factory=list)
    # T1 replay, T2 arrows, T3 accounting, T4 determinism, T5 roundtrip
    checks: dict[str, dict] = Field(default_factory=dict)


def validate(d: TimingDiagram) -> list[str]:
    """Checks a schema cannot express. Returns issues; never raises."""
    out: list[str] = []
    lanes = {ln.id: ln for dm in d.domains for ln in dm.lanes}
    ids = [ln.id for dm in d.domains for ln in dm.lanes]
    if len(set(ids)) != len(ids):
        out.append("duplicate lane id")
    for a in d.arrows:
        for end in (a.src, a.dst):
            ln = lanes.get(end.lane)
            if ln is None:
                out.append(f"{a.id}: unknown lane {end.lane}")
            elif not any(s.cycle == end.cycle for s in ln.values):
                out.append(f"{a.id}: {end.lane} has no drawn sample at cycle {end.cycle}")
        if a.kind == "same" and a.regs != 0:
            out.append(f"{a.id}: same-cycle arrow through {a.regs} register(s)")
        if a.kind == "next" and a.regs != 1:
            out.append(f"{a.id}: next-cycle arrow through {a.regs} register(s)")
        if not a.path:
            out.append(f"{a.id}: no dependency path")
    for w in d.windows:
        if w.t1 < w.t0:
            out.append(f"window {w.t0}..{w.t1} is empty")
    for g in d.gaps:
        if g.until_t <= g.after_t:
            out.append(f"gap {g.after_t}..{g.until_t} is empty")
    return out
