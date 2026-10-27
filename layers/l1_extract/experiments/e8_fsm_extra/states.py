"""e8 states: state values, encoding, RTL naming and the Moore/Mealy output rule.

Library module (no CLI), loaded by e8_extract.py:

    uv run --package rtl2d-l1 python layers/l1_extract/experiments/e8_fsm_extra/e8_extract.py ...

Encoding (derived from the integer state values, first match wins):
  onehot  every value is a distinct power of two
  gray    >= 3 states, every non-self transition flips exactly one bit and those transitions
          contain a ring through all states (Hamming-1 ring)
  enum    the register is declared with an enum type (values not one-hot / gray)
  binary  distinct known integer values
  other   a value is unknown or two names share a value
"""

from __future__ import annotations

import re

from pyslang import ast

from rtl2d_l1.frontend import fsm as l1fsm
from rtl2d_l1.frontend.fsm_semantic import _cv_int, _mask, _parse_const
from rtl2d_l1.frontend.graph import EdgeType

UNNAMED = re.compile(r"^S_(\d+)$")


def find_var(design, G, key: str):
    """The VariableSymbol / NetSymbol of a graph node, or None."""
    inst = l1fsm._find_instance(design, G.nodes[key].inst)
    if inst is None:
        return None
    for m in l1fsm._members(inst.body):
        if isinstance(m, (ast.VariableSymbol, ast.NetSymbol)) and m.hierarchicalPath == key:
            return m
    return None


def is_enum(design, G, key: str) -> bool:
    v = find_var(design, G, key)
    try:
        return v is not None and v.type.canonicalType.kind == ast.SymbolKind.EnumType
    except Exception:
        return False


def enum_map(design, G, key: str) -> dict[str, int]:
    v = find_var(design, G, key)
    out: dict[str, int] = {}
    try:
        ct = v.type.canonicalType if v is not None else None
        if ct is not None and ct.kind == ast.SymbolKind.EnumType:
            for ev in ct:
                if isinstance(ev, ast.EnumValueSymbol):
                    out[ev.name] = _cv_int(ev.value)[0]
    except Exception:
        pass
    return out


def params_of(design, inst_path: str) -> dict[str, int]:
    inst = l1fsm._find_instance(design, inst_path)
    out: dict[str, int] = {}
    if inst is None:
        return out
    for m in inst.body:
        if isinstance(m, ast.ParameterSymbol):
            try:
                out[m.name] = _cv_int(m.value)[0]
            except Exception:
                continue
    return out


def const_map(design, G, key: str, insts: list[str]) -> dict[str, int]:
    """name -> value for enum literals of the register's type and parameters of the register's
    instance, then of the other instances in `insts` (the register's instance wins)."""
    out = dict(enum_map(design, G, key))
    for path in [G.nodes[key].inst, *[p for p in insts if p != G.nodes[key].inst]]:
        for n, v in params_of(design, path).items():
            out.setdefault(n, v)
    return out


def alias_value_names(design, G, key: str, insts: list[str]) -> dict[int, dict]:
    """value -> {name, inst} from parameters of *other* instances that hold a port alias or the
    next-state logic of the register; values with two different names are dropped."""
    out: dict[int, dict] = {}
    dup: set[int] = set()
    width = G.nodes[key].width or 1
    for path in insts:
        if path == G.nodes[key].inst:
            continue
        inst = l1fsm._find_instance(design, path)
        locs = {m.name: m for m in (inst.body if inst is not None else [])
                if isinstance(m, ast.ParameterSymbol)}
        for n, v in params_of(design, path).items():
            v &= _mask(width)
            if v in out and out[v]["name"] != n:
                dup.add(v)
            sym = locs.get(n)
            loc = {"file": design.file_of(sym), "line": design.line_of(sym)} if sym else {}
            out.setdefault(v, {"name": n, "inst": path, **loc})
    return {v: x for v, x in out.items() if v not in dup}


def state_values(states: list[dict], cmap: dict[str, int], width: int) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for s in states:
        v = None
        if s.get("value"):
            try:
                v = _parse_const(str(s["value"]))[0]
            except Exception:
                v = None
        if v is None:
            v = cmap.get(s["name"])
        out[s["name"]] = None if v is None else v & _mask(width)
    return out


def _pow2(v: int) -> bool:
    return v > 0 and v & (v - 1) == 0


def _ham_ring(vals: dict[str, int], edges: set[tuple[str, str]]) -> bool:
    names = sorted(vals)
    n = len(names)
    if n < 3 or n > 12:
        return False
    adj = {a: {b for x, b in edges if x == a} for a in names}
    start = names[0]

    def dfs(cur, seen):
        if len(seen) == n:
            return start in adj[cur]
        return any(dfs(b, seen | {b}) for b in sorted(adj[cur]) if b not in seen)

    return dfs(start, {start})


def encoding(values: dict[str, int | None], transitions: list[dict], enum_typed: bool) -> str:
    vals = list(values.values())
    if not vals or any(v is None for v in vals) or len(set(vals)) != len(vals):
        return "other"
    if len(vals) >= 2 and all(_pow2(v) for v in vals):
        return "onehot"
    edges = set()
    for t in transitions:
        a, b = t["src"], t["dst"]
        if a in values and b in values and a != b:
            edges.add((a, b))
    if (
        len(vals) >= 3
        and edges
        and all(bin(values[a] ^ values[b]).count("1") == 1 for a, b in edges)
        and _ham_ring(values, edges)
    ):
        return "gray"
    if enum_typed:
        return "enum"
    return "binary"


def unnamed_states(values: dict[str, int | None], cmap: dict[str, int]) -> list[str]:
    """States whose name is the S_<v> fallback or a bare literal (no RTL constant name)."""
    out = []
    for n, v in values.items():
        if n in cmap:
            continue
        m = UNNAMED.match(n)
        if (m and v is not None and int(m.group(1)) == v) or l1fsm._lit_value(n) is not None:
            out.append(n)
    return out


def outputs_rule(G, S: str, reads: set[str], targets: set[str]) -> list[dict]:
    """fsm.extract_fsms' Moore/Mealy output rule, applied to the register and its port aliases:
    an output is a top/instance output port or a pure decode of the state; Mealy when a
    combinational path from an input port reaches it."""
    insts = {G.nodes[k].inst for k in reads}
    outs = []
    for k, n in G.nodes.items():
        if n.inst not in insts or k in targets or k in reads:
            continue
        preds = {p for p, et in G.preds(k) if et not in (EdgeType.CLOCK, EdgeType.RESET)} - {k}
        if not preds & reads:
            continue
        is_port = n.port_dir == "out"
        pure_decode = not n.is_state and preds <= reads
        if not (is_port or pure_decode):
            continue
        kind = (
            "mealy" if (not n.is_state and l1fsm._comb_from_input(G, k, targets | reads))
            else "moore"
        )
        outs.append({"signal": n.name, "kind": kind, "port": is_port})
    return sorted(outs, key=lambda o: (not o["port"], o["signal"]))
