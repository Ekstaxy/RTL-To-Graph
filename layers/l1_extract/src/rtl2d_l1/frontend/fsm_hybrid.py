"""Hybrid FSM extraction: syntactic labels where they are trustworthy, semantic truth always.

* every syntactic FSM is cross-checked against the semantic (execution-based) state graph;
  `semantic_check` = consistent | mismatch | unsupported
* FSMs only the semantic engine finds (one-hot bit equations, next-state logic in a submodule,
  if-chains with compound guards, ...) are added; their state names come from constants of the
  design with the same value, and their transition conditions are derived by enumerating the
  module's 1-bit inputs and minimizing with Quine-McCluskey.
"""

from __future__ import annotations

import itertools

import networkx as nx
from pyslang import ast

from .elab import Design
from .entities import EntityTable
from .fsm import FSM, Transition, extract_fsms
from .fsm_semantic import Machine, SemanticFSM, _cv_int, _mask, analyze, detect, state_graph
from .graph import DesignGraph, EdgeType


# ------------------------------------------------------------ Quine-McCluskey
def _qm(minterms: set[int], dontcares: set[int], nbits: int) -> list[str]:
    """Prime implicant cover (greedy) as patterns over '0','1','-' (MSB first)."""
    if not minterms:
        return []
    terms = {format(m, f"0{nbits}b") for m in minterms | dontcares}
    primes = set()
    while terms:
        nxt, used = set(), set()
        tl = sorted(terms)
        for a, b in itertools.combinations(tl, 2):
            diff = [i for i in range(nbits) if a[i] != b[i]]
            if len(diff) == 1 and "-" not in (a[diff[0]], b[diff[0]]):
                nxt.add(a[: diff[0]] + "-" + a[diff[0] + 1 :])
                used |= {a, b}
        primes |= set(tl) - used
        terms = nxt

    def covers(p, m):
        s = format(m, f"0{nbits}b")
        return all(c == "-" or c == s[i] for i, c in enumerate(p))

    need, cover = set(minterms), []
    while need:
        best = max(primes, key=lambda p: (sum(covers(p, m) for m in need), p.count("-")))
        cover.append(best)
        need = {m for m in need if not covers(best, m)}
    return cover


def _cube_text(p: str, names: list[str]) -> str:
    lits = [(n if c == "1" else f"!{n}") for c, n in zip(p, names, strict=False) if c != "-"]
    return " && ".join(lits) if lits else "1"


# ------------------------------------------------------------------ helpers
def _value_names(design: Design, G: DesignGraph, key: str) -> dict[int, str]:
    """value -> constant name, from enum literals of the register's type or parameters of its
    scope."""
    out: dict[int, str] = {}
    n = G.nodes[key]
    inst_path = n.inst
    stack = list(design.tops)
    inst = None
    while stack:
        s = stack.pop()
        if s.hierarchicalPath == inst_path:
            inst = s
            break
        stack += [m for m in s.body if isinstance(m, ast.InstanceSymbol)]
    if inst is None:
        return out
    seen_dupe = set()
    for m in inst.body:
        if isinstance(m, ast.ParameterSymbol):
            try:
                v, _ = _cv_int(m.value)
            except Exception:
                continue
            if v in out and out[v] != m.name:
                seen_dupe.add(v)
            out.setdefault(v, m.name)
        if isinstance(m, ast.VariableSymbol) and m.hierarchicalPath == key:
            ct = m.type.canonicalType
            if ct.kind == ast.SymbolKind.EnumType:
                for ev in ct:
                    if isinstance(ev, ast.EnumValueSymbol):
                        out[_cv_int(ev.value)[0]] = ev.name
                return out
    return {v: nm for v, nm in out.items() if v not in seen_dupe}


def _control_inputs(
    G: DesignGraph, key: str, exclude: set[str], limit: int = 8
) -> list[tuple[str, int, str]]:
    """Control bits of the next-state cone, nearest first: (node key, bit, label). Top-level input
    ports up to 4 bits wide are split into bits; 1-bit registers are included as well."""
    out, seen, frontier = [], {key}, [key]
    for _ in range(8):
        nxt = []
        for k in frontier:
            for p, et in G.preds(k):
                if p in seen or et in (EdgeType.CLOCK, EdgeType.RESET):
                    continue
                seen.add(p)
                pn = G.nodes[p]
                if p in exclude:
                    continue
                if pn.port_dir == "in" and pn.inst in G.tops and 1 <= pn.width <= 4:
                    if pn.width == 1:
                        out.append((p, 0, pn.name))
                    else:
                        out += [(p, b, f"{pn.name}[{b}]") for b in range(pn.width)]
                elif pn.width == 1 and pn.is_state:
                    out.append((p, 0, pn.name))
                if not pn.is_state:
                    nxt.append(p)
        frontier = nxt
    return out[:limit]


def _conditions(
    design, G, M: Machine, r: SemanticFSM, width: int, repeats: int = 6
) -> list[Transition]:
    """Transitions with conditions over the 1-bit control inputs (other values sampled)."""
    ctrl = _control_inputs(G, r.state, {r.reset_signal} if r.reset_signal else set())
    labels = [c[2] for c in ctrl]
    inactive = (
        {r.reset_signal: 1 - r.reset_level}
        if r.reset_signal is not None and r.reset_level is not None
        else {}
    )
    out = []
    for s in r.states:
        by_dst: dict[int, set[int]] = {}
        dont = set()
        for combo in range(1 << len(ctrl)):
            dsts = set()
            for _ in range(repeats):
                env = {r.state: s, **inactive}
                for i, (k, b, _) in enumerate(ctrl):
                    bit = (combo >> (len(ctrl) - 1 - i)) & 1
                    env[k] = (env.get(k, 0) & ~(1 << b)) | (bit << b)
                M.new_cycle(env)
                nb = M.next_values(r.state)
                dsts.add(nb.get(r.state, s) & _mask(width))
            if len(dsts) == 1:
                by_dst.setdefault(dsts.pop(), set()).add(combo)
            else:  # depends on non-control values (datapath compare): record each with a marker
                for d in dsts:
                    by_dst.setdefault(d, set())
                dont.add(combo)
        for d, mins in by_dst.items():
            cubes = _qm(mins, set(), len(ctrl)) if mins else []
            cond = " || ".join(
                f"({_cube_text(c, labels)})" if len(cubes) > 1 else _cube_text(c, labels)
                for c in cubes
            )
            if not cubes and dont:
                cond = "<datapath condition>"
            elif dont and d not in (s,):
                cond = (cond + " || " if cond else "") + "<datapath condition>"
            out.append(Transition(src=str(s), dst=str(d), cond=cond or "1"))
    return out


def _syntactic_graph(f: FSM):
    names = [s["name"] for s in f.states]
    g = nx.DiGraph()
    for n in names:
        g.add_node(n, reset=(n == f.reset_state))
    for t in f.transitions:
        for a in names if t.src == "*" else [t.src]:
            if a != t.dst:
                g.add_edge(a, t.dst)
    return g


def _retry_consistent(design, G, key, f, M) -> bool:
    r = analyze(design, G, key, machine=M, samples_per_state=1500, seed=7)
    return not r.error and nx.is_isomorphic(
        _syntactic_graph(f), state_graph(r), node_match=lambda a, b: a["reset"] == b["reset"]
    )


def _executed_subset(f: FSM, r: SemanticFSM, key: str, design, G) -> bool:
    """Map executed state values to syntactic state names; True if executed edges ⊆ syntactic
    edges."""
    from .fsm_semantic import _parse_const

    by_val = {}
    for s in f.states:
        try:
            v, _, _ = _parse_const(s["value"]) if s["value"] else (None, None, None)
        except Exception:
            v = None
        if v is not None:
            by_val[v & _mask(G.nodes[key].width)] = s["name"]
    if not by_val:
        vn = _value_names(design, G, key)
        by_val = {v: n for v, n in vn.items()}
    syn = set(_syntactic_graph(f).edges())
    try:
        mapped = {(by_val[a], by_val[b]) for a, b in r.edges if a != b}
    except KeyError:
        return False
    return mapped <= syn and by_val.get(r.reset_value) == f.reset_state


def extract_fsms_hybrid(
    design: Design,
    G: DesignGraph,
    tables: list[EntityTable],
    extra_state_ids: dict[str, set[str]] | None = None,
) -> list[FSM]:
    syn = extract_fsms(design, G, tables, extra_state_ids)
    syn_keys = {}
    for f in syn:
        key = f"{f.instance}.{f.state}"
        if key in G.nodes:
            syn_keys[key] = f
    try:
        sem = detect(design, G, set(syn_keys))
    except Exception as ex:  # never let the semantic engine break the pipeline
        for f in syn:
            f.warnings.append(f"semantic check unavailable: {type(ex).__name__}")
        return syn
    sem_by_key = {r.state: r for r in sem}
    out = []
    M = Machine(design, 1)
    for key, f in syn_keys.items():
        r = sem_by_key.get(key)
        if r is None or r.error:
            f.warnings.append(f"semantic_check: unsupported ({r.error if r else 'not analyzed'})")
            f.semantic_check = "unsupported"
        elif nx.is_isomorphic(
            _syntactic_graph(f), state_graph(r), node_match=lambda a, b: a["reset"] == b["reset"]
        ):
            f.semantic_check = "consistent"
        elif _retry_consistent(design, G, key, f, M):
            f.semantic_check = "consistent"
        elif _executed_subset(f, r, key, design, G):
            # every executed transition is in the syntactic FSM; execution just did not reach the
            # rest
            # (deep states need several datapath conditions at once): keep the syntactic result
            f.semantic_check = "consistent-subset"
        else:
            f.semantic_check = "mismatch"
            f.warnings.append(
                f"semantic_check: mismatch (syntactic {len(f.states)} states / "
                f"{_syntactic_graph(f).number_of_edges()} edges vs executed {len(r.states)} / "
                f"{state_graph(r).number_of_edges()}); semantic transitions attached"
            )
            f.semantic_transitions = [
                t.__dict__ for t in _conditions(design, G, M, r, G.nodes[key].width)
            ]
        out.append(f)
    for r in sem:
        if r.state in syn_keys or r.error:
            continue
        n = G.nodes[r.state]
        vn = _value_names(design, G, r.state)
        name = lambda v, vn=vn: vn.get(v, f"S_{v}")  # noqa: E731
        trans = _conditions(design, G, M, r, n.width)
        f = FSM(
            module=n.module,
            instance=n.inst,
            state=n.rel,
            next=None,
            style="semantic",
            states=[{"name": name(v), "value": str(v)} for v in r.states],
            reset_state=name(r.reset_value),
            transitions=[
                Transition(src=name(int(t.src)), dst=name(int(t.dst)), cond=t.cond) for t in trans
            ],
            outputs=[],
            warnings=["extracted by execution (coding style not recognized syntactically)"],
        )
        f.semantic_check = "semantic-only"
        out.append(f)
    return out
