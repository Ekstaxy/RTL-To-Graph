"""Experiment-local Diagram model and checks.

Follows the format proposed in docs/adr/0002-diagram-minimal-core.md. This is NOT the
contract: `rtl2d_contracts.diagram` is still a stub. Move to the contract once it exists.

Check files: `python spec.py <diagram.json> [...]`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SCHEMA_VERSION = "0.1.0"
ID_PATTERN = r"^[A-Za-z0-9_.\-]+$"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Block(_Model):
    id: str = Field(pattern=ID_PATTERN)
    label: str
    kind: str | None = None
    parent_id: str | None = None


class Port(_Model):
    id: str = Field(pattern=ID_PATTERN)
    owner_block_id: str | None
    direction: Literal["input", "output"]
    width: int = Field(ge=1)
    class_: str | None = Field(default=None, alias="class")


class Net(_Model):
    id: str = Field(pattern=ID_PATTERN)
    source: str
    targets: list[str] = Field(min_length=1)
    width: int = Field(ge=1)
    class_: str | None = Field(default=None, alias="class")


class Diagram(_Model):
    schema_version: str
    blocks: list[Block]
    ports: list[Port]
    nets: list[Net]


def validate(d: Diagram) -> list[str]:
    """Checks the schema cannot express (ADR-0002 rules 1-6). Returns issues, never raises."""
    issues: list[str] = []
    if d.schema_version != SCHEMA_VERSION:
        issues.append(f"schema_version is {d.schema_version!r}, expected {SCHEMA_VERSION!r}")

    seen: set[str] = set()
    for obj in [*d.blocks, *d.ports, *d.nets]:
        if obj.id in seen:
            issues.append(f"duplicate id {obj.id!r}")
        seen.add(obj.id)

    blocks = {b.id: b for b in d.blocks}
    ports = {p.id: p for p in d.ports}

    for b in d.blocks:
        if b.parent_id is not None and b.parent_id not in blocks:
            issues.append(f"block {b.id!r}: parent_id {b.parent_id!r} does not exist")
        chain, cur = {b.id}, b.parent_id
        while cur is not None and cur in blocks:
            if cur in chain:
                issues.append(f"block {b.id!r}: parent_id cycle")
                break
            chain.add(cur)
            cur = blocks[cur].parent_id

    for p in d.ports:
        if p.owner_block_id is not None and p.owner_block_id not in blocks:
            issues.append(f"port {p.id!r}: owner_block_id {p.owner_block_id!r} does not exist")

    drives: dict[str, str] = {}
    sinks: dict[str, str] = {}
    for n in d.nets:
        for role, pid in [("source", n.source), *(("target", t) for t in n.targets)]:
            p = ports.get(pid)
            if p is None:
                issues.append(f"net {n.id!r}: {role} {pid!r} does not exist")
                continue
            boundary = p.owner_block_id is None
            # A boundary input drives the inside of the design; a boundary output is a sink.
            can_drive = (p.direction == "output") != boundary
            if (role == "source") != can_drive:
                where = "boundary" if boundary else "block"
                issues.append(f"net {n.id!r}: {role} {pid!r} is a {where} {p.direction}")
            if p.width != n.width:
                issues.append(f"net {n.id!r}: width {n.width} != port {pid!r} width {p.width}")
            used = drives if role == "source" else sinks
            if pid in used:
                issues.append(f"port {pid!r} is a {role} of both {used[pid]!r} and {n.id!r}")
            used[pid] = n.id
    return issues


def load(path: Path) -> tuple[Diagram | None, list[str]]:
    """Parse and validate a file. Returns (diagram or None, issues)."""
    try:
        d = Diagram.model_validate_json(path.read_text())
    except (ValidationError, json.JSONDecodeError) as e:
        return None, [f"schema: {line}" for line in str(e).splitlines()[:8]]
    return d, validate(d)


def dump(d: Diagram, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d.model_dump(by_alias=True), indent=2) + "\n")


def main(argv: list[str]) -> int:
    bad = 0
    for arg in argv:
        d, issues = load(Path(arg))
        if issues:
            bad += 1
            print(f"FAIL {arg}")
            for i in issues:
                print(f"  - {i}")
        else:
            print(f"ok   {arg}  blocks={len(d.blocks)} ports={len(d.ports)} nets={len(d.nets)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
