"""Deterministic variants of a Diagram, for stressing L3.

Every function takes a Diagram and returns a new one. `VALID` variants must still pass
`spec.validate`; `INVALID` variants each break exactly one rule and must be caught.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from spec import Diagram

GLOBAL_CLASSES = {"clock", "reset"}


def _copy(d: Diagram) -> Diagram:
    return d.model_copy(deep=True)


def no_meta(d: Diagram) -> Diagram:
    """Drop every optional label: kind and class become null (L3 must fall back to boxes)."""
    d = _copy(d)
    for obj in [*d.blocks, *d.ports, *d.nets]:
        if hasattr(obj, "kind"):
            obj.kind = None
        else:
            obj.class_ = None
    return d


def no_global(d: Diagram) -> Diagram:
    """Remove clock/reset nets and their ports (the 'clk is not a wire' presentation)."""
    d = _copy(d)
    d.nets = [n for n in d.nets if n.class_ not in GLOBAL_CLASSES]
    d.ports = [p for p in d.ports if p.class_ not in GLOBAL_CLASSES]
    return d


def shuffled(d: Diagram, seed: int = 0) -> Diagram:
    """Same graph, different list order. Output should not depend on input order."""
    d = _copy(d)
    rng = random.Random(seed)
    for items in (d.blocks, d.ports, d.nets, *(n.targets for n in d.nets)):
        rng.shuffle(items)
    return d


def long_labels(d: Diagram) -> Diagram:
    """Realistic long instance names, to stress text measurement and block sizing."""
    d = _copy(d)
    for b in d.blocks:
        b.label = f"u_{b.label.lower().replace(' ', '_')}_gen_inst[{len(b.label)}]"
    return d


def flat(d: Diagram) -> Diagram:
    """Remove hierarchy: drop blocks that only act as parents, clear parent_id."""
    d = _copy(d)
    owners = {p.owner_block_id for p in d.ports}
    parents = {b.parent_id for b in d.blocks}
    d.blocks = [b for b in d.blocks if b.id in owners or b.id not in parents]
    for b in d.blocks:
        b.parent_id = None
    return d


def mirrored(d: Diagram, copies: int = 2) -> Diagram:
    """N independent copies in one diagram (parallel channels, disconnected components)."""
    out = _copy(d)
    out.blocks, out.ports, out.nets = [], [], []
    for k in range(copies):
        c = _copy(d)
        tag = f"ch{k}."

        def ren(x: str | None, tag: str = tag) -> str | None:
            return None if x is None else tag + x

        for b in c.blocks:
            b.id, b.parent_id, b.label = ren(b.id), ren(b.parent_id), f"{b.label} [{k}]"
        for p in c.ports:
            p.id, p.owner_block_id = ren(p.id), ren(p.owner_block_id)
        for n in c.nets:
            n.id, n.source, n.targets = ren(n.id), ren(n.source), [ren(t) for t in n.targets]
        out.blocks += c.blocks
        out.ports += c.ports
        out.nets += c.nets
    return out


# --- invalid on purpose (one broken rule each) ---


def bad_dangling_target(d: Diagram) -> Diagram:
    d = _copy(d)
    d.nets[0].targets.append("does.not.exist")
    return d


def bad_width(d: Diagram) -> Diagram:
    d = _copy(d)
    d.nets[0].width += 1
    return d


def bad_duplicate_id(d: Diagram) -> Diagram:
    d = _copy(d)
    d.blocks.append(d.blocks[0].model_copy())
    return d


def bad_direction(d: Diagram) -> Diagram:
    d = _copy(d)
    n = d.nets[0]
    n.source, n.targets[0] = n.targets[0], n.source
    return d


def bad_double_driver(d: Diagram) -> Diagram:
    d = _copy(d)
    extra = d.nets[1].model_copy(deep=True)
    extra.id += "_dup"
    d.nets.append(extra)
    return d


def bad_parent_cycle(d: Diagram) -> Diagram:
    d = _copy(d)
    a, b = d.blocks[0], d.blocks[1]
    a.parent_id, b.parent_id = b.id, a.id
    return d


Variant = Callable[[Diagram], Diagram]

VALID: dict[str, Variant] = {
    "base": _copy,
    "no_meta": no_meta,
    "no_global": no_global,
    "shuffled": shuffled,
    "long_labels": long_labels,
    "flat": flat,
    "x2": mirrored,
}

INVALID: dict[str, Variant] = {
    "bad_dangling_target": bad_dangling_target,
    "bad_width": bad_width,
    "bad_duplicate_id": bad_duplicate_id,
    "bad_direction": bad_direction,
    "bad_double_driver": bad_double_driver,
    "bad_parent_cycle": bad_parent_cycle,
}
