"""e9 helpers: bounded walks over the L1 DesignGraph and RTL source-line lookups.

Library module (no command line). e9_select.py bootstraps this file through importlib and then
loads templates.py / clock_domains.py with `sibling()`, so nothing depends on sys.path.

A *walk* starts at a port and follows typed edges through combinational nodes only; it stops
at the first register (any `is_state` node, memories included) on each path. Each reached
register keeps the edge list of the first (shortest, then lexicographically smallest) path,
so evidence strings can cite `via` lines.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections import deque
from functools import lru_cache
from pathlib import Path

from rtl2d_l1.frontend.graph import DesignGraph, EdgeType

HERE = Path(__file__).resolve().parent
FLOW = frozenset({EdgeType.DATA, EdgeType.CONTROL, EdgeType.ADDR, EdgeType.PORT})
DATAISH = frozenset({EdgeType.DATA, EdgeType.ADDR, EdgeType.PORT})

# one edge of a path: (src, dst, type value, via)
Edge = tuple[str, str, str, str]


def sibling(name: str):
    """Load e9_protocol_templates/<name>.py under the module name `e9_<name>` (no sys.path)."""
    mod_name = name if name.startswith("e9_") else f"e9_{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _neighbors(G: DesignGraph, k: str, types, forward: bool) -> list[tuple[str, str, str]]:
    """(other end, edge type value, via), sorted for determinism."""
    edges = G.g.out_edges(k, data=True) if forward else G.g.in_edges(k, data=True)
    out = []
    for s, t, d in edges:
        if d["type"] in types:
            out.append((t if forward else s, d["type"].value, d["via"]))
    return sorted(out)


def walk_regs(
    G: DesignGraph,
    start: str,
    *,
    forward: bool = True,
    types=FLOW,
    max_hops: int = 3,
    skip: frozenset[str] = frozenset(),
) -> dict[str, list[Edge]]:
    """Registers reached from `start` within `max_hops` edges through combinational nodes.

    A register `start` itself is returned with an empty path (an output port that is a
    register drives itself). Nodes in `skip` (clock/reset nets) are never entered."""
    if G.nodes[start].is_state and not forward:
        return {start: []}
    found: dict[str, list[Edge]] = {}
    seen = {start}
    q: deque[tuple[str, list[Edge]]] = deque([(start, [])])
    while q:
        k, path = q.popleft()
        if len(path) >= max_hops:
            continue
        for o, et, via in _neighbors(G, k, types, forward):
            if o in seen or o in skip or o not in G.nodes:
                continue
            seen.add(o)
            # paths are always kept in source-to-sink order (fmt_path relies on it)
            p2 = [*path, (k, o, et, via)] if forward else [(o, k, et, via), *path]
            if G.nodes[o].is_state:
                found[o] = p2
            else:
                q.append((o, p2))
    return found


def gated(paths: dict[str, list[Edge]]) -> dict[str, list[Edge]]:
    """Registers whose path contains a CONTROL edge (the port gates their write)."""
    return {r: p for r, p in paths.items() if any(e[2] == "CONTROL" for e in p)}


def data_only(paths: dict[str, list[Edge]]) -> dict[str, list[Edge]]:
    """Registers reached on a path with no CONTROL edge (value flow)."""
    return {r: p for r, p in paths.items() if all(e[2] != "CONTROL" for e in p)}


_LOOP_HEAD = r"\bfor\s*\(\s*(?:integer\s+|int\s+|genvar\s+|automatic\s+)?{}\s*="


def is_loop_index(G: DesignGraph, k: str) -> bool:
    """True for a for-loop index: L1 `loop_var`, or an integer/genvar that the source uses as
    `for (name = ...` (L1 reports a module-scope `integer i` used inside an always block as
    is_state=True, loop_var=False)."""
    n = G.nodes[k]
    if n.loop_var:
        return True
    if not re.match(r"(integer|int|genvar)\b", n.type_str or ""):
        return False
    pat = re.compile(_LOOP_HEAD.format(re.escape(n.name)))
    return any(pat.search(ln) for ln in source_lines(n.file))


def is_counter(G: DesignGraph, k: str) -> bool:
    """A register updated from itself through +/- (L1 arith_srcs), at least 2 bits wide, not a
    memory and not a for-loop index."""
    n = G.nodes[k]
    return (n.is_state and n.width >= 2 and n.depth is None and k in n.arith_srcs
            and not is_loop_index(G, k))


def rel(G: DesignGraph, k: str) -> str:
    return G.nodes[k].rel if k in G.nodes else k


def fmt_path(G: DesignGraph, path: list[Edge]) -> str:
    """`a -CONTROL-> b (always_ff@L34)` style, one hop per arrow."""
    if not path:
        return ""
    parts = [rel(G, path[0][0])]
    for _s, t, et, via in path:
        parts.append(f"-{et}({via})-> {rel(G, t)}")
    return " ".join(parts)


@lru_cache(maxsize=64)
def source_lines(path: str) -> tuple[str, ...]:
    try:
        return tuple(Path(path).read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return ()


_VIA_LINE = re.compile(r"@L(\d+)$")


def via_line(via: str) -> int | None:
    m = _VIA_LINE.search(via or "")
    return int(m.group(1)) if m else None


def block_text(file: str, line: int, max_lines: int = 60) -> str:
    """Source of the procedure starting at `line` (1-based), up to the next always/assign/
    initial/endmodule keyword at the start of a line or `max_lines` lines."""
    lines = source_lines(file)
    if not line or line > len(lines):
        return ""
    out = [lines[line - 1]]
    stop = re.compile(r"^\s*(always\w*|assign|initial|endmodule)\b")
    for ln in lines[line : line - 1 + max_lines]:
        if stop.match(ln):
            break
        out.append(ln)
    return "\n".join(out)


def sensitivity(file: str, line: int) -> str | None:
    """Text inside `@( ... )` of the procedure at `line`, or None (e.g. always_comb)."""
    head = " ".join(source_lines(file)[line - 1 : line + 2]) if line else ""
    head = re.sub(r"//.*?$", "", head)
    m = re.search(r"@\s*\(([^)]*)\)", head)
    return m.group(1) if m else None


def gaters(
    G: DesignGraph, x: str, top: str, *, max_hops: int = 3, skip: frozenset[str] = frozenset()
) -> dict[str, list[Edge]]:
    """Registers and top ports whose value decides *whether* `x` is written: backward walk from
    `x` through combinational nodes, keeping sources whose path holds a CONTROL edge."""
    found: dict[str, list[Edge]] = {}
    seen = {x}
    q: deque[tuple[str, list[Edge]]] = deque([(x, [])])
    while q:
        k, path = q.popleft()
        if len(path) >= max_hops:
            continue
        for o, et, via in _neighbors(G, k, FLOW, False):
            if o in seen or o in skip or o not in G.nodes:
                continue
            seen.add(o)
            p2 = [(o, k, et, via), *path]
            n = G.nodes[o]
            if n.is_state or (n.port_dir and n.inst == top):
                if any(e[2] == "CONTROL" for e in p2):
                    found[o] = p2
            else:
                q.append((o, p2))
    return found


def reg_distances(
    G: DesignGraph, starts: list[str], top: str, max_cost: int, *, max_edges: int = 6,
    skip: frozenset[str] = frozenset(),
) -> dict[str, tuple[int, str]]:
    """Undirected distance over FLOW edges counting only registers and top ports (entering a
    combinational net is free), at most `max_edges` raw edges; {node: (cost, nearest start)}.
    So a register wired to a member through any `assign` chain is 1 hop away."""
    best: dict[str, tuple[int, int, str]] = {}
    dq: deque[tuple[str, int, int, str]] = deque()
    for s in sorted(starts):
        best[s] = (0, 0, s)
        dq.append((s, 0, 0, s))
    while dq:
        k, c, e, origin = dq.popleft()
        if best.get(k, (c, e, origin))[:2] < (c, e) or e >= max_edges:
            continue
        nbs = {o for o, _t, _v in _neighbors(G, k, FLOW, True)}
        nbs |= {o for o, _t, _v in _neighbors(G, k, FLOW, False)}
        for o in sorted(nbs):
            if o in skip or o not in G.nodes:
                continue
            n = G.nodes[o]
            step = 1 if n.is_state or (n.port_dir and n.inst == top) else 0
            c2 = c + step
            if c2 > max_cost or (o in best and best[o][:2] <= (c2, e + 1)):
                continue
            best[o] = (c2, e + 1, origin)
            if step:
                dq.append((o, c2, e + 1, origin))
            else:
                dq.appendleft((o, c2, e + 1, origin))
    return {k: (v[0], v[2]) for k, v in best.items()}
