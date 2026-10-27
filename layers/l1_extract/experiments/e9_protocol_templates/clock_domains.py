"""e9 clock domains and resets of the top module (plan §3 Stage 1, `clock_domains.py`).

Library module (no command line); used by e9_select.py.

* domain(reg) = the CLOCK predecessors of the register, each traced back to its root net
  through single-source DATA/PORT chains of combinational nodes (`assign wclk = i_wclk;`,
  `.clk(clk)`), seeded with `entities.clock_reset_nets`. Domain id = `d.<root name>`.
* a port's domain = domains of the registers it drives (input) or is driven by (output)
  within 3 hops through combinational nodes; several -> `cdc`.
* resets: RESET-edge sources traced to roots the same way; polarity from use (`negedge r`,
  `if (!r)`, `if (r)`), else from the name; sync vs async from the sensitivity list of every
  procedure the reset appears in (async when the reset net is in `@(...)`).
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from rtl2d_l1.frontend.entities import clock_reset_nets
from rtl2d_l1.frontend.graph import DesignGraph, EdgeType

_g = None


def _graph_mod():
    global _g
    if _g is None:
        import importlib.util
        import sys

        name = "e9_graph"
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                name, Path(__file__).resolve().parent / "e9_graph.py"
            )
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        _g = sys.modules[name]
    return _g


_LOW_NAME = re.compile(r"(_n|n|_ni|_b|_l)$|^n_?(rst|reset)", re.I)


def trace_root(G: DesignGraph, k: str) -> tuple[str, list[str]]:
    """Follow single-source DATA/PORT predecessors of combinational nodes back to the root.
    Returns (root key, chain of keys from k to the root inclusive)."""
    chain = [k]
    seen = {k}
    while True:
        n = G.nodes[k]
        if n.is_state or n.port_dir == "in" and n.inst in G.tops:
            break
        ps = sorted({p for p, _et in G.preds(k, {EdgeType.DATA, EdgeType.PORT}) if p != k})
        if len(ps) != 1 or ps[0] in seen:
            break
        k = ps[0]
        seen.add(k)
        chain.append(k)
    return k, chain


def _inverted(G: DesignGraph, chain: list[str]) -> bool:
    """Odd number of `~`/`!` inversions along an assign chain (read from the source lines)."""
    gm = _graph_mod()
    inv = 0
    for a, b in zip(chain, chain[1:], strict=False):  # a is driven by b
        for _s, _t, d in G.g.in_edges(a, data=True):
            if _s != b or d["type"] not in (EdgeType.DATA, EdgeType.PORT):
                continue
            ln = gm.via_line(d["via"])
            text = gm.source_lines(G.nodes[a].file)[ln - 1] if ln else ""
            name_b = re.escape(G.nodes[b].name)
            if re.search(rf"[~!]\s*\(?\s*{name_b}\b", text):
                inv += 1
            break
    return inv % 2 == 1


def domain_id(G: DesignGraph, root: str) -> str:
    return "d." + G.nodes[root].rel


class Domains:
    """Clock domains of one elaborated design, queried for the top module's ports/regs."""

    def __init__(self, G: DesignGraph, top: str):
        self.G, self.top = G, top
        self.notes: list[str] = []
        clk_nets, rst_nets = clock_reset_nets(G)
        self.clk_nets, self.rst_nets = set(clk_nets), set(rst_nets)
        self.reg_domain: dict[str, str] = {}
        self.root_edges: dict[str, Counter] = {}
        self._clock_roots()
        self.cr_nets = frozenset(self.clk_nets | self.rst_nets)

    def _clock_roots(self) -> None:
        G = self.G
        gm = _graph_mod()
        for t in sorted(G.nodes):
            cps = sorted({p for p, _et in G.preds(t, {EdgeType.CLOCK})})
            if not cps:
                continue
            doms = []
            for c in cps:
                root, chain = trace_root(G, c)
                self.clk_nets.update(chain)
                doms.append(domain_id(G, root))
                cnt = self.root_edges.setdefault(root, Counter())
                d = G.g.get_edge_data(c, t, key=EdgeType.CLOCK.value)
                ln = gm.via_line(d["via"]) if d else None
                sens = gm.sensitivity(G.nodes[t].file, ln) if ln else None
                m = re.search(rf"(posedge|negedge)\s+{re.escape(G.nodes[c].name)}\b", sens or "")
                edge = m.group(1) if m else "unknown"
                if _inverted(G, chain):
                    edge = {"posedge": "negedge", "negedge": "posedge"}.get(edge, edge)
                cnt[edge] += 1
            doms = sorted(set(doms))
            self.reg_domain[t] = doms[0]
            if len(doms) > 1:
                self.notes.append(
                    f"{G.nodes[t].rel}: written under {len(doms)} clocks {doms}; domain "
                    f"{doms[0]} used (first sorted)"
                )

    # ---------------------------------------------------------------- clocks
    def clocks(self) -> list[dict]:
        G, out = self.G, []
        for root in sorted(self.root_edges, key=lambda k: (G.nodes[k].line, k)):
            n = G.nodes[root]
            edges = self.root_edges[root]
            edge = edges.most_common(1)[0][0]
            if len(edges) > 1:
                self.notes.append(
                    f"clock {n.rel}: mixed edges {dict(sorted(edges.items()))}; '{edge}' reported"
                )
            if not (n.port_dir == "in" and n.inst == self.top):
                self.notes.append(
                    f"clock root {n.key} (line {n.line}) is not a top input port; domain "
                    f"{domain_id(G, root)} kept, not listed in clocks"
                )
                continue
            out.append({"port": n.name, "domain": domain_id(G, root), "edge": edge,
                        "line": n.line})
        return out

    def all_domains(self) -> list[str]:
        return sorted(set(self.reg_domain.values()))

    # ---------------------------------------------------------------- ports
    def port_domain(self, k: str) -> tuple[str | None, str]:
        """(domain, how). Input: registers it drives; output: registers driving it (3 hops)."""
        G = self.G
        gm = _graph_mod()
        n = G.nodes[k]
        if n.is_state and k in self.reg_domain:
            return self.reg_domain[k], "register port"
        regs = gm.walk_regs(G, k, forward=n.port_dir == "in", max_hops=3, skip=self.cr_nets)
        doms = sorted({self.reg_domain[r] for r in regs if r in self.reg_domain})
        if len(doms) == 1:
            return doms[0], f"via {len(regs)} register(s)"
        if len(doms) > 1:
            return "cdc", f"registers in {doms}"
        alld = self.all_domains()
        if len(alld) == 1:
            return alld[0], "no register within 3 hops; only domain of the design assumed"
        if not alld:
            return None, "no register within 3 hops and the design has no clock domain"
        return None, f"no register within 3 hops and {len(alld)} domains: unknown"

    # ---------------------------------------------------------------- resets
    def resets(self) -> list[dict]:
        G, gm = self.G, _graph_mod()
        by_root: dict[str, list[tuple[str, str, str, list[str]]]] = {}
        for s, t, d in sorted(G.g.edges(data=True), key=lambda e: (e[0], e[1])):
            if d["type"] != EdgeType.RESET:
                continue
            root, chain = trace_root(G, s)
            by_root.setdefault(root, []).append((s, t, d["via"], chain))
        out = []
        for root in sorted(by_root, key=lambda k: (G.nodes[k].line, k)):
            n = G.nodes[root]
            uses = by_root[root]
            low_votes, kinds, ev = Counter(), Counter(), []
            lines_by_kind: dict[str, set] = {}
            doms = sorted({self.reg_domain[t] for _s, t, _v, _c in uses if t in self.reg_domain})
            for s, t, via, chain in uses:
                ln = gm.via_line(via)
                f = G.nodes[t].file
                sens = gm.sensitivity(f, ln) if ln else None
                name = re.escape(G.nodes[s].name)
                inv = _inverted(G, chain)
                m = re.search(rf"(posedge|negedge)\s+{name}\b", sens or "")
                kinds["async" if m else "sync"] += 1
                lines_by_kind.setdefault("async" if m else "sync", set()).add(ln)
                body = gm.block_text(f, ln) if ln else ""
                if m:
                    low = m.group(1) == "negedge"
                elif re.search(rf"[!~]\s*{name}\b|\b{name}\s*==\s*(1'b0|1'h0|0)\b", body):
                    low = True
                elif re.search(rf"if\s*\(\s*{name}\s*\)|\b{name}\s*==\s*(1'b1|1'h1|1)\b", body):
                    low = False
                else:
                    continue
                low_votes[low != inv] += 1
            if low_votes:
                active_low = low_votes.most_common(1)[0][0]
                ev.append(f"polarity from use {dict(low_votes)} (True=active low)")
                if len(low_votes) > 1:
                    self.notes.append(f"reset {n.rel}: conflicting polarity uses {dict(low_votes)}")
            else:
                active_low = bool(_LOW_NAME.search(n.name))
                ev.append("polarity from name only")
                self.notes.append(f"reset {n.rel}: polarity from name only (active_low="
                                  f"{active_low})")
            if kinds["async"] and kinds["sync"]:
                sync = None
                self.notes.append(
                    f"reset {n.rel}: async in {kinds['async']} register writes (procedures at "
                    f"lines {sorted(lines_by_kind['async'])}) and sync in {kinds['sync']} "
                    f"(lines {sorted(lines_by_kind['sync'])}); sync=null")
            else:
                sync = not kinds["async"]
            if not (n.port_dir == "in" and n.inst == self.top):
                self.notes.append(f"reset root {n.key} (line {n.line}) is not a top input port; "
                                  "not listed in resets")
                continue
            out.append({"port": n.name, "active_low": active_low, "sync": sync,
                        "domains": doms, "line": n.line})
        return out
