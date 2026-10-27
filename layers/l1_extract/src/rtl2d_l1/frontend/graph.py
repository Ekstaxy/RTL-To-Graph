"""Typed dependency graph built directly from slang's elaborated AST (SPEC §2.1).

Nodes are elaborated value symbols keyed by hierarchical path. Edges are typed:
DATA / CONTROL / ADDR / CLOCK / RESET / PORT. No synthesis is involved, so the
original names and the procedural control structure survive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

import networkx as nx
import pyslang
from pyslang import ast

from .elab import Design


class EdgeType(str, Enum):
    DATA = "DATA"
    CONTROL = "CONTROL"
    ADDR = "ADDR"
    CLOCK = "CLOCK"
    RESET = "RESET"
    PORT = "PORT"


_PROC_KIND = {
    ast.ProceduralBlockKind.AlwaysFF: "always_ff",
    ast.ProceduralBlockKind.AlwaysComb: "always_comb",
    ast.ProceduralBlockKind.AlwaysLatch: "always_latch",
    ast.ProceduralBlockKind.Always: "always",
    ast.ProceduralBlockKind.Initial: "initial",
    ast.ProceduralBlockKind.Final: "final",
}

_CLOCK_NAME = re.compile(r"(^|_)(clk|clock|ck)(_|$|\d)", re.I)
_RESET_NAME = re.compile(
    r"(^|_)(n?rst|rst_?n|n?reset|reset_?n|a?resetn?|clr|clear|srst|arst)(_|$)", re.I
)
_DIR = {
    ast.ArgumentDirection.In: "in",
    ast.ArgumentDirection.Out: "out",
    ast.ArgumentDirection.InOut: "inout",
    ast.ArgumentDirection.Ref: "inout",
}


@dataclass
class Node:
    key: str
    name: str
    inst: str
    module: str
    rel: str
    kind: str  # "net" | "var"
    width: int
    depth: int | None
    type_str: str
    enum_values: list[str]
    line: int
    file: str
    offset: int = 0
    local: bool = False
    loop_var: bool = False
    case_selector: bool = False  # decoded as a whole value: `case (x)` or `x == CONST`
    port_dir: str | None = None
    driven_by: set[str] = field(default_factory=set)
    is_state: bool = False
    is_latch: bool = False
    const_assigns: int = 0
    arith_srcs: set[str] = field(default_factory=set)  # sources combined with +/- (counter-like)


@dataclass
class InstanceInfo:
    path: str
    name: str
    module: str
    parent: str | None
    line: int
    file: str
    ports: dict[str, str] = field(default_factory=dict)  # port name -> node key
    port_dirs: dict[str, str] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)


@dataclass
class Reads:
    data: set[str] = field(default_factory=set)
    ctrl: set[str] = field(default_factory=set)
    addr: set[str] = field(default_factory=set)
    const_only: bool = True
    partial: set[str] = field(default_factory=set)  # data read only through bit/part selects

    def merge(self, o: Reads) -> Reads:
        full = (self.data - self.partial) | (o.data - o.partial)
        self.data |= o.data
        self.ctrl |= o.ctrl
        self.addr |= o.addr
        self.const_only &= o.const_only
        self.partial = (self.partial | o.partial) - full
        return self

    def all(self) -> set[str]:
        return self.data | self.ctrl | self.addr


@dataclass
class Proc:
    kind: str
    line: int
    clocked: bool = False
    clocks: set[str] = field(default_factory=set)
    resets: set[str] = field(default_factory=set)

    @property
    def via(self) -> str:
        return f"{self.kind}@L{self.line}"


def _has_arith(e) -> bool:
    """True if the expression contains a + / - (counter-like update)."""
    if e is None:
        return False
    if isinstance(e, ast.BinaryExpression):
        if str(e.op).split(".")[-1] in ("Add", "Subtract"):
            return True
        return _has_arith(e.left) or _has_arith(e.right)
    if isinstance(e, ast.ConditionalExpression):
        return _has_arith(e.left) or _has_arith(e.right)
    if isinstance(e, (ast.ConversionExpression, ast.UnaryExpression)):
        return _has_arith(e.operand)
    if isinstance(e, ast.ConcatenationExpression):
        return any(_has_arith(x) for x in e.operands)
    return False


class DesignGraph:
    def __init__(self, design: Design):
        self.design = design
        self.g = nx.MultiDiGraph()
        self.nodes: dict[str, Node] = {}
        self.instances: dict[str, InstanceInfo] = {}
        self.tops: list[str] = []
        self.unsupported: list[str] = []

    # ---- construction helpers -------------------------------------------------
    def add_edge(
        self, src: str, dst: str, etype: EdgeType, via: str, partial: bool = False
    ) -> None:
        if src == dst and etype not in (EdgeType.DATA, EdgeType.CONTROL):
            return
        data = self.g.get_edge_data(src, dst, default={})
        for d in data.values():
            if d["type"] == etype:
                if not partial:
                    d["partial"] = False  # read as a whole somewhere: not partial
                return
        self.g.add_edge(src, dst, key=etype.value, type=etype, via=via, partial=partial)

    def is_partial(self, src: str, dst: str) -> bool:
        d = self.g.get_edge_data(src, dst, default={}).get(EdgeType.DATA.value)
        return bool(d and d.get("partial"))

    # ---- queries ----------------------------------------------------------------
    def nodes_of_instance(self, inst_path: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.inst == inst_path]

    def preds(self, key: str, types: set[EdgeType] | None = None) -> list[tuple[str, EdgeType]]:
        out = []
        for s, _, d in self.g.in_edges(key, data=True):
            if types is None or d["type"] in types:
                out.append((s, d["type"]))
        return out

    def succs(self, key: str, types: set[EdgeType] | None = None) -> list[tuple[str, EdgeType]]:
        out = []
        for _, t, d in self.g.out_edges(key, data=True):
            if types is None or d["type"] in types:
                out.append((t, d["type"]))
        return out

    def stats(self) -> dict:
        by_type: dict[str, int] = {}
        for _, _, d in self.g.edges(data=True):
            by_type[d["type"].value] = by_type.get(d["type"].value, 0) + 1
        return {
            "nodes": self.g.number_of_nodes(),
            "edges": self.g.number_of_edges(),
            "instances": len(self.instances),
            "edges_by_type": by_type,
            "state_nodes": sum(1 for n in self.nodes.values() if n.is_state),
        }

    def to_json(self) -> dict:
        return {
            "design": self.design.name,
            "tops": self.tops,
            "instances": {
                p: {
                    "module": i.module,
                    "parent": i.parent,
                    "ports": i.ports,
                    "port_dirs": i.port_dirs,
                    "line": i.line,
                }
                for p, i in self.instances.items()
            },
            "nodes": {
                k: {
                    "name": n.name,
                    "inst": n.inst,
                    "module": n.module,
                    "rel": n.rel,
                    "kind": n.kind,
                    "width": n.width,
                    "depth": n.depth,
                    "type": n.type_str,
                    "port_dir": n.port_dir,
                    "driven_by": sorted(n.driven_by),
                    "is_state": n.is_state,
                    "line": n.line,
                }
                for k, n in self.nodes.items()
            },
            "edges": [
                {"src": s, "dst": t, "type": d["type"].value, "via": d["via"]}
                for s, t, d in self.g.edges(data=True)
            ],
        }


class _Builder:
    def __init__(self, design: Design):
        self.struct_resets: set[str] = set()
        self.name_resets: set[str] = set()
        self.async_resets: set[str] = set()
        self.d = design
        self.G = DesignGraph(design)

    # ------------------------------------------------------------------ symbols
    def node(self, sym, *, local: bool = False) -> str | None:
        if sym is None or sym.kind not in (ast.SymbolKind.Net, ast.SymbolKind.Variable):
            return None
        key = sym.hierarchicalPath
        if key in self.G.nodes:
            return key
        # owning instance is resolved after the walk (_resolve_owners): longest instance-path prefix
        inst_path, module, rel = "", "", sym.name
        t = sym.type
        ct = t.canonicalType
        width, depth = t.bitWidth, None
        if ct.isUnpackedArray:
            depth = 1
            et = ct
            while et is not None and et.isUnpackedArray:
                try:
                    depth *= max(1, et.fixedRange.width)
                except Exception:
                    pass
                et = et.arrayElementType
            width = et.bitWidth if et is not None else 0
        enum_values: list[str] = []
        if ct.kind == ast.SymbolKind.EnumType:
            enum_values = [m.name for m in ct if isinstance(m, ast.EnumValueSymbol)]
        n = Node(
            key=key,
            name=sym.name,
            inst=inst_path,
            module=module,
            rel=rel,
            kind="net" if sym.kind == ast.SymbolKind.Net else "var",
            width=int(width or 0),
            depth=depth,
            type_str=str(t),
            enum_values=enum_values,
            line=self.d.line_of(sym),
            file=self.d.file_of(sym),
            offset=int(sym.location.offset),
            local=local,
        )
        self.G.nodes[key] = n
        self.G.g.add_node(key)
        return key

    # ------------------------------------------------------------- expressions
    def reads(self, e) -> Reads:
        r = Reads()
        if e is None:
            return r
        if isinstance(e, ast.ValueExpressionBase):
            sym = e.symbol
            k = self.node(sym)
            if k:
                r.data.add(k)
                r.const_only = False
            return r
        if isinstance(e, ast.ConditionalExpression):
            for c in e.conditions:
                r.ctrl |= self.reads(c.expr).all()
            r.const_only = False
            r.merge(self.reads(e.left))
            r.merge(self.reads(e.right))
            return r
        if isinstance(e, ast.ElementSelectExpression):
            v = self.reads(e.value)
            v.partial |= v.data
            r.merge(v)
            sel = self.reads(e.selector)
            r.addr |= sel.all()
            r.const_only &= sel.const_only
            return r
        if isinstance(e, ast.RangeSelectExpression):
            v = self.reads(e.value)
            v.partial |= v.data
            r.merge(v)
            for x in (e.left, e.right):
                s = self.reads(x)
                r.addr |= s.all()
            return r
        if isinstance(e, ast.UnaryExpression):
            return self.reads(e.operand)
        if isinstance(e, ast.BinaryExpression):
            lr, rr = self.reads(e.left), self.reads(e.right)
            if str(e.op).split(".")[-1] in (
                "Equality",
                "Inequality",
                "CaseEquality",
                "CaseInequality",
            ):
                # `state == IDLE`: a whole value compared with a constant (FSM-style decoding)
                for side, other in ((e.left, rr), (e.right, lr)):
                    s0 = side
                    while isinstance(s0, ast.ConversionExpression):
                        s0 = s0.operand
                    if isinstance(s0, ast.ValueExpressionBase) and not other.all():
                        k = self.node(s0.symbol)
                        if k:
                            self.G.nodes[k].case_selector = True
            return r.merge(lr).merge(rr)
        if isinstance(e, ast.ConcatenationExpression):
            for x in e.operands:
                r.merge(self.reads(x))
            return r
        if isinstance(e, ast.ReplicationExpression):
            return self.reads(e.concat)
        if isinstance(e, ast.ConversionExpression):
            return self.reads(e.operand)
        if isinstance(e, ast.MemberAccessExpression):
            return self.reads(e.value)
        if isinstance(e, ast.AssignmentExpression):
            return self.reads(e.right)
        if isinstance(e, ast.InsideExpression):
            r.merge(self.reads(e.left))
            for x in e.rangeList:
                r.merge(self.reads(x))
            return r
        if isinstance(e, ast.CallExpression):
            for x in e.arguments:
                r.merge(self.reads(x))
            if not e.isSystemCall:
                r.const_only = False
            return r
        # generic fallback: every referenced value is a DATA read
        found: list = []

        def _cb(n):
            if isinstance(n, ast.ValueExpressionBase):
                found.append(n.symbol)
            return True

        try:
            e.visit(_cb)
        except Exception:
            pass
        for sym in found:
            k = self.node(sym)
            if k:
                r.data.add(k)
                r.const_only = False
        return r

    def lvalue(self, e) -> tuple[list[str], set[str]]:
        """Return (target node keys, index/select read keys)."""
        if e is None:
            return [], set()
        if isinstance(e, ast.ValueExpressionBase):
            k = self.node(e.symbol)
            return ([k] if k else []), set()
        if isinstance(e, ast.ElementSelectExpression):
            t, a = self.lvalue(e.value)
            return t, a | self.reads(e.selector).all()
        if isinstance(e, ast.RangeSelectExpression):
            t, a = self.lvalue(e.value)
            return t, a | self.reads(e.left).all() | self.reads(e.right).all()
        if isinstance(e, ast.MemberAccessExpression):
            return self.lvalue(e.value)
        if isinstance(e, ast.ConversionExpression):
            return self.lvalue(e.operand)
        if isinstance(e, ast.ConcatenationExpression):
            ts, addr = [], set()
            for x in e.operands:
                t, a = self.lvalue(x)
                ts += t
                addr |= a
            return ts, addr
        if isinstance(e, ast.StreamingConcatenationExpression):
            ts, addr = [], set()
            for s in e.streams:
                t, a = self.lvalue(s.operand)
                ts += t
                addr |= a
            return ts, addr
        try:
            sym = e.getSymbolReference()
            k = self.node(sym)
            return ([k] if k else []), set()
        except Exception:
            return [], set()

    def assign(
        self,
        lhs,
        rhs,
        ctrl: set[str],
        rst: set[str],
        proc: Proc,
        *,
        compound=False,
        rhs_reads: Reads | None = None,
    ):
        targets, addr_l = self.lvalue(lhs)
        r = rhs_reads if rhs_reads is not None else self.reads(rhs)
        G = self.G
        for t in targets:
            n = G.nodes[t]
            n.driven_by.add(proc.kind)
            if proc.clocked:
                n.is_state = True
            if proc.kind == "always_latch":
                n.is_latch = True
            if (
                not r.data and not r.addr
            ):  # constant, or constants selected by conditions (x ? S1 : S0)
                n.const_assigns += 1
            if r.data and _has_arith(rhs):
                n.arith_srcs |= r.data
            for s in r.data:
                G.add_edge(s, t, EdgeType.DATA, proc.via, partial=s in r.partial)
            for s in r.ctrl | ctrl:
                if s in rst:
                    continue
                G.add_edge(s, t, EdgeType.CONTROL, proc.via)
            for s in r.addr | addr_l:
                G.add_edge(s, t, EdgeType.ADDR, proc.via)
            for s in rst:
                G.add_edge(s, t, EdgeType.RESET, proc.via)
            for s in proc.clocks:
                G.add_edge(s, t, EdgeType.CLOCK, proc.via)
            if compound:
                G.add_edge(t, t, EdgeType.DATA, proc.via)

    # -------------------------------------------------------------- statements
    def stmt(self, st, ctrl: set[str], rst: set[str], proc: Proc, first: bool = False):
        if st is None:
            return
        if isinstance(st, ast.BlockStatement):
            # first-level-ness passes through begin/end
            return self.stmt(st.body, ctrl, rst, proc, first)
        if isinstance(st, ast.StatementList):
            items = list(st.list)
            for i, x in enumerate(items):
                # a reset may also be written as a trailing override:
                # `case(...) ... endcase; if (reset) s <= S0;`
                last_if = i == len(items) - 1 and isinstance(x, ast.ConditionalStatement)
                self.stmt(x, ctrl, rst, proc, first and (len(items) == 1 or last_if))
            return
        if isinstance(st, ast.TimedStatement):
            return self.stmt(st.stmt, ctrl, rst, proc, first)
        if isinstance(st, ast.ConditionalStatement):
            cond: set[str] = set()
            for c in st.conditions:
                cond |= self.reads(c.expr).all()
            if cond and self._is_reset_cond(cond, proc, first, st):
                # `if (!rst || !valid)`: only the known reset is a reset, the rest is control
                known = cond & proc.resets
                rsig = known if known else cond
                proc.resets |= rsig
                self.stmt(st.ifTrue, ctrl | (cond - rsig), rst | rsig, proc)
                self.stmt(st.ifFalse, ctrl | (cond - rsig), rst | rsig, proc)
            else:
                self.stmt(st.ifTrue, ctrl | cond, rst, proc)
                self.stmt(st.ifFalse, ctrl | cond, rst, proc)
            return
        if isinstance(st, (ast.CaseStatement, ast.PatternCaseStatement)):
            sel = self.reads(st.expr).all()
            for k in sel:
                self.G.nodes[k].case_selector = True
            if isinstance(st, ast.CaseStatement):
                for it in st.items:
                    for x in it.expressions:
                        sel |= self.reads(x).all()
            for it in st.items:
                self.stmt(it.stmt, ctrl | sel, rst, proc)
            self.stmt(st.defaultCase, ctrl | sel, rst, proc)
            return
        if isinstance(st, ast.ForLoopStatement):
            for v in st.loopVars:
                k = self.node(v, local=True)
                if k:
                    self.G.nodes[k].loop_var = True
            for x in st.initializers:
                if isinstance(x, ast.AssignmentExpression):
                    self.assign(x.left, x.right, ctrl, rst, proc)
            stop = self.reads(st.stopExpr).all()
            return self.stmt(st.body, ctrl | stop, rst, proc)
        if isinstance(st, (ast.WhileLoopStatement, ast.DoWhileLoopStatement)):
            return self.stmt(st.body, ctrl | self.reads(st.cond).all(), rst, proc)
        if isinstance(st, ast.RepeatLoopStatement):
            return self.stmt(st.body, ctrl | self.reads(st.count).all(), rst, proc)
        if isinstance(st, (ast.ForeachLoopStatement, ast.ForeverLoopStatement)):
            return self.stmt(st.body, ctrl, rst, proc)
        if isinstance(st, ast.VariableDeclStatement):
            k = self.node(st.symbol, local=True)
            if k and st.symbol.initializer is not None:
                self._assign_to_key(k, st.symbol.initializer, ctrl, rst, proc)
            return
        if isinstance(st, ast.ExpressionStatement):
            e = st.expr
            if isinstance(e, ast.AssignmentExpression):
                self.assign(e.left, e.right, ctrl, rst, proc, compound=e.isCompound)
            elif isinstance(e, ast.UnaryExpression):  # i++ / --i
                t, _ = self.lvalue(e.operand)
                for k in t:
                    self.G.nodes[k].driven_by.add(proc.kind)
                    if proc.clocked:
                        self.G.nodes[k].is_state = True
                    self.G.add_edge(k, k, EdgeType.DATA, proc.via)
            return
        # Empty, Return, Disable, assertions, event triggers, ... : no dataflow

    def _assign_to_key(self, key, rhs, ctrl, rst, proc):
        r = self.reads(rhs)
        n = self.G.nodes[key]
        n.driven_by.add(proc.kind)
        for s in r.data:
            self.G.add_edge(s, key, EdgeType.DATA, proc.via)
        for s in r.ctrl | ctrl:
            self.G.add_edge(s, key, EdgeType.CONTROL, proc.via)
        for s in r.addr:
            self.G.add_edge(s, key, EdgeType.ADDR, proc.via)

    def _is_reset_cond(self, cond: set[str], proc: Proc, first: bool, st=None) -> bool:
        """Async reset = first-level condition on an edge signal. Sync reset = a 1-bit condition
        that is either reset-named (any nesting depth, e.g. `if (EN) if (Rst)`), or --
        structurally, so it survives obfuscated names -- a 1-bit input port tested by the
        first-level `if` of a clocked block whose taken branch assigns only constants."""
        if proc.clocked and first and cond & proc.resets:
            return True
        if len(cond) != 1:
            return False
        n = self.G.nodes[next(iter(cond))]
        if n.width != 1:
            return False
        if _RESET_NAME.search(n.name):
            self.name_resets.add(n.key)
            return True
        if proc.clocked and first and st is not None and n.port_dir == "in":
            all_const, n_assign = self._const_branch(st.ifTrue)
            if all_const and n_assign >= 1:
                self.struct_resets.add(n.key)
                return True
        return False

    def _const_branch(self, st) -> tuple[bool, int]:
        """(every assignment in `st` writes a constant, number of assignments)."""
        if st is None:
            return True, 0
        if isinstance(st, ast.BlockStatement):
            return self._const_branch(st.body)
        if isinstance(st, ast.TimedStatement):
            return self._const_branch(st.stmt)
        if isinstance(st, ast.StatementList):
            ok, n = True, 0
            for x in st.list:
                o, k = self._const_branch(x)
                ok &= o
                n += k
            return ok, n
        if isinstance(st, ast.ConditionalStatement):
            o1, n1 = self._const_branch(st.ifTrue)
            o2, n2 = self._const_branch(st.ifFalse)
            return o1 and o2, n1 + n2
        if isinstance(st, ast.ForLoopStatement):  # reset loops: for (i..) mem[i] <= 0
            return self._const_branch(st.body)
        if isinstance(st, ast.ExpressionStatement) and isinstance(
            st.expr, ast.AssignmentExpression
        ):
            r = self.reads(st.expr.right)
            loopish = {k for k in r.all() if self.G.nodes[k].loop_var}
            return not ((r.data | r.addr) - loopish), 1
        if isinstance(st, ast.EmptyStatement) if hasattr(ast, "EmptyStatement") else False:
            return True, 0
        return False, 0

    # ------------------------------------------------------------- procedures
    def proc(self, pb: ast.ProceduralBlockSymbol):
        kind = _PROC_KIND.get(pb.procedureKind, "always")
        if kind == "final":
            return
        p = Proc(kind=kind, line=self.d.line_of(pb))
        body = pb.body
        edge_sigs: list[str] = []
        if isinstance(body, ast.TimedStatement):
            evs = []
            t = body.timing
            if isinstance(t, ast.EventListControl):
                evs = list(t.events)
            elif isinstance(t, ast.SignalEventControl):
                evs = [t]
            for ev in evs:
                if isinstance(ev, ast.SignalEventControl) and ev.edge in (
                    ast.EdgeKind.PosEdge,
                    ast.EdgeKind.NegEdge,
                    ast.EdgeKind.BothEdges,
                ):
                    edge_sigs += sorted(self.reads(ev.expr).all())
        if kind == "always_ff" or edge_sigs:
            p.clocked = True
            if kind == "always":
                p.kind = "always_ff"  # edge-triggered legacy always == flop
        if p.clocked:
            # async resets = edge signals that are the condition of the first-level if
            first_cond = self._first_condition(body)
            async_rst = set(edge_sigs) & first_cond
            # extra edge signals named like resets are resets even if the first `if` tests another
            # signal (buggy-but-legal RTL such as `@(posedge clk or negedge arstn) if (!brstn)`)
            async_rst |= {
                k
                for k in edge_sigs
                if _RESET_NAME.search(self.G.nodes[k].name) and self.G.nodes[k].width == 1
            }
            clocks = set(edge_sigs) - async_rst
            if len(clocks) > 1:
                named = {k for k in clocks if _CLOCK_NAME.search(self.G.nodes[k].name)}
                if named:
                    async_rst |= clocks - named
                    clocks = named
            p.resets = set(async_rst)
            self.async_resets |= async_rst
            p.clocks = clocks or ({edge_sigs[0]} if edge_sigs else set())
        if kind == "initial":
            return  # initial blocks: simulation init only, ignored for architecture
        if isinstance(body, ast.InvalidStatement):
            # slang drops the whole block when a branch that is dead under the current parameters
            # would be illegal (e.g. a reversed part-select) and suppresses the diagnostic; recover
            # the dataflow from the syntax tree instead of losing every assignment in the block
            self._syntax_proc(pb, p)
            return
        self.stmt(body, set(), set(), p, first=True)

    # ------------------------------------------------- syntax fallback (invalid blocks)
    def _syn_keys(self, syn, scope) -> list[str]:
        """Graph nodes referenced by identifiers under a syntax node, in source order."""
        out: list[str] = []
        stack = [syn]
        while stack:
            n = stack.pop()
            if n is None:
                continue
            if isinstance(n, pyslang.parsing.Token):
                if n.kind == pyslang.parsing.TokenKind.Identifier:
                    try:
                        sym = scope.lookupName(n.valueText)
                    except Exception:
                        sym = None
                    k = self.node(sym) if sym is not None else None
                    if k and k not in out:
                        out.append(k)
                continue
            try:
                stack.extend(reversed(list(n)))
            except TypeError:
                pass
        return out

    def _syntax_proc(self, pb, p: Proc) -> None:
        scope = pb.parentScope
        syn = pb.syntax
        self.G.unsupported.append(f"syntax-fallback dataflow for invalid block at {p.via}")
        st = syn.statement
        if st.kind == pyslang.syntax.SyntaxKind.TimingControlStatement:
            timing = st.timingControl
            toks = []
            stack = [timing]
            while stack:
                n = stack.pop()
                if isinstance(n, pyslang.parsing.Token):
                    toks.append(n.kind)
                else:
                    try:
                        stack.extend(list(n))
                    except TypeError:
                        pass
            if pyslang.parsing.TokenKind.PosEdgeKeyword in toks or (
                pyslang.parsing.TokenKind.NegEdgeKeyword in toks
            ):
                p.clocked = True
                p.kind = "always_ff"
                edge = self._syn_keys(timing, scope)
                clocks = [k for k in edge if _CLOCK_NAME.search(self.G.nodes[k].name)] or edge[:1]
                p.clocks = set(clocks)
                p.resets = set(edge) - p.clocks  # extra edge signals: async resets
                self.async_resets |= p.resets
            st = st.statement
        self._syn_stmt(st, scope, set(), p, set(), first=True)

    def _syn_stmt(self, n, scope, ctrl: set[str], p: Proc, rst: set[str], first=False) -> None:
        SK = pyslang.syntax.SyntaxKind
        if n is None or isinstance(n, pyslang.parsing.Token):
            return
        k = n.kind
        if k == SK.SequentialBlockStatement:
            items = list(n.items)
            for i, x in enumerate(items):
                # a reset may be the first `if` or a trailing override `if (rst) ...` at the end
                edge = len(items) == 1 or i == 0 or i == len(items) - 1
                self._syn_stmt(x, scope, ctrl, p, rst, first and edge)
            return
        if k in (SK.AssignmentExpression, SK.NonblockingAssignmentExpression) or (
            k.name.endswith("AssignmentExpression") and hasattr(n, "left")
        ):
            lhs = self._syn_keys(n.left, scope)
            data = self._syn_keys(n.right, scope)
            if not lhs:
                return
            tgt, addr = lhs[0], lhs[1:]
            node = self.G.nodes[tgt]
            node.driven_by.add(p.kind)
            if not data:
                node.const_assigns += 1
            if p.clocked:
                node.is_state = True
            for s in data:
                self.G.add_edge(s, tgt, EdgeType.DATA, p.via)
            for s in ctrl:
                self.G.add_edge(s, tgt, EdgeType.CONTROL, p.via)
            for s in rst:
                self.G.add_edge(s, tgt, EdgeType.RESET, p.via)
            for s in addr:
                self.G.add_edge(s, tgt, EdgeType.ADDR, p.via)
            return
        if k == SK.ConditionalStatement:
            cond = set(self._syn_keys(n.predicate, scope))
            is_rst = (
                p.clocked
                and first
                and len(cond) == 1
                and (
                    cond <= p.resets
                    or (
                        self.G.nodes[next(iter(cond))].width == 1
                        and _RESET_NAME.search(self.G.nodes[next(iter(cond))].name)
                    )
                )
            )
            if is_rst:
                self.name_resets |= cond - p.resets
                c2, r2 = ctrl, rst | cond
            else:
                c2, r2 = ctrl | cond, rst
            self._syn_stmt(n.statement, scope, c2, p, r2)
            if n.elseClause is not None:
                self._syn_stmt(n.elseClause.clause, scope, c2, p, r2)
            return
        if k in (SK.CaseStatement, SK.RandCaseStatement):
            sel = set(self._syn_keys(n.expr, scope))
            for x in sel:
                self.G.nodes[x].case_selector = True
            for it in n.items:
                self._syn_stmt(it, scope, ctrl | sel, p, rst)
            return
        if k in (
            SK.ForLoopStatement,
            SK.LoopStatement,
            SK.DoWhileStatement,
            SK.ForeachLoopStatement,
        ):
            stop = set(
                self._syn_keys(getattr(n, "stopExpr", None) or getattr(n, "expr", None), scope)
            )
            self._syn_stmt(n.statement, scope, ctrl | stop, p, rst)
            return
        try:
            children = list(n)
        except TypeError:
            return
        for c in children:
            self._syn_stmt(c, scope, ctrl, p, rst)

    def _first_condition(self, st) -> set[str]:
        guard = 0
        while st is not None and guard < 10:
            guard += 1
            if isinstance(st, ast.TimedStatement):
                st = st.stmt
            elif isinstance(st, ast.BlockStatement):
                st = st.body
            elif isinstance(st, ast.StatementList) and len(list(st.list)) == 1:
                st = list(st.list)[0]
            elif isinstance(st, ast.ConditionalStatement):
                s: set[str] = set()
                for c in st.conditions:
                    s |= self.reads(c.expr).all()
                return s
            else:
                return set()
        return set()

    # ------------------------------------------------------------- hierarchy
    def instance(self, inst: ast.InstanceSymbol, parent: str | None):
        if not inst.isModule:
            self.G.unsupported.append(f"non-module instance {inst.hierarchicalPath}")
            return
        path = inst.hierarchicalPath
        info = InstanceInfo(
            path=path,
            name=inst.name,
            module=inst.definition.name,
            parent=parent,
            line=self.d.line_of(inst),
            file=self.d.file_of(inst),
        )
        self.G.instances[path] = info
        if parent:
            self.G.instances[parent].children.append(path)
        body = inst.body
        for p in body.portList:
            if isinstance(p, ast.PortSymbol) and p.internalSymbol is not None:
                k = self.node(p.internalSymbol)
                if k:
                    d = _DIR.get(p.direction, "inout")
                    self.G.nodes[k].port_dir = d
                    info.ports[p.name] = k
                    info.port_dirs[p.name] = d
                    if parent is None and d in ("in", "inout"):
                        self.G.nodes[k].driven_by.add("port_in")
            elif isinstance(p, ast.InterfacePortSymbol):
                self.G.unsupported.append(f"interface port {path}.{p.name} (name-level only)")
        self.scope(body, path)

    def connect(self, inst: ast.InstanceSymbol):
        if not inst.isModule:
            return
        via = f"inst:{inst.name}@L{self.d.line_of(inst)}"
        for pc in inst.portConnections:
            port = pc.port
            if not isinstance(port, ast.PortSymbol) or port.internalSymbol is None:
                continue
            e = pc.expression
            if e is None:
                continue
            child = self.node(port.internalSymbol)
            if not child:
                continue
            d = _DIR.get(port.direction, "inout")
            if d in ("in", "inout"):
                r = self.reads(e.right if isinstance(e, ast.AssignmentExpression) else e)
                for s in r.data:
                    self.G.add_edge(s, child, EdgeType.PORT, via)
                for s in r.ctrl:
                    self.G.add_edge(s, child, EdgeType.CONTROL, via)
                for s in r.addr:
                    self.G.add_edge(s, child, EdgeType.ADDR, via)
                self.G.nodes[child].driven_by.add("port_in")
            if d in ("out", "inout"):
                lhs = e.left if isinstance(e, ast.AssignmentExpression) else e
                targets, addr = self.lvalue(lhs)
                for t in targets:
                    self.G.add_edge(child, t, EdgeType.PORT, via)
                    self.G.nodes[t].driven_by.add("inst_out")
                    for a in addr:
                        self.G.add_edge(a, t, EdgeType.ADDR, via)

    def scope(self, scope, inst_path: str):
        for m in scope:
            if isinstance(m, (ast.NetSymbol, ast.VariableSymbol)):
                k = self.node(m)
                if k and isinstance(m, ast.NetSymbol) and m.initializer is not None:
                    self._assign_to_key(
                        k, m.initializer, set(), set(), Proc("assign", self.d.line_of(m))
                    )
            elif isinstance(m, ast.ContinuousAssignSymbol):
                a = m.assignment
                if isinstance(a, ast.AssignmentExpression):
                    self.assign(a.left, a.right, set(), set(), Proc("assign", self.d.line_of(m)))
            elif isinstance(m, ast.ProceduralBlockSymbol):
                self.proc(m)
            elif isinstance(m, ast.InstanceSymbol):
                self.instance(m, inst_path)
                self.connect(m)
            elif isinstance(m, ast.InstanceArraySymbol):
                self._inst_array(m, inst_path)
            elif isinstance(m, ast.GenerateBlockSymbol):
                if not m.isUninstantiated:
                    self.scope(m, inst_path)
            elif isinstance(m, ast.GenerateBlockArraySymbol):
                for e in m.entries:
                    if not e.isUninstantiated:
                        self.scope(e, inst_path)

    def _inst_array(self, arr, inst_path):
        for el in arr.elements:
            if isinstance(el, ast.InstanceSymbol):
                self.instance(el, inst_path)
                self.connect(el)
            elif isinstance(el, ast.InstanceArraySymbol):
                self._inst_array(el, inst_path)

    def build(self) -> DesignGraph:
        for top in self.d.tops:
            self.G.tops.append(top.hierarchicalPath)
            self.instance(top, None)
        self._resolve_owners()
        self._fix_reset_clocks()
        self._demote_false_resets()
        return self.G

    def _demote_false_resets(self):
        """Sync-reset guesses that are really control signals become CONTROL again:
        * structural guesses (1-bit input gating constant-only branches) that are also used as
          data/control elsewhere -- a valid/stall input in low-power coding styles;
        * internal signals named like resets that are driven by ordinary logic (an FSM-driven
          `reset_crc`): a datapath clear, not a reset."""
        G = self.G
        resets = {s for s, _, d in G.g.edges(data=True) if d["type"] == EdgeType.RESET}
        demote = set()
        for k in self.struct_resets - self.async_resets:
            if any(et in (EdgeType.DATA, EdgeType.ADDR) for _, et in G.succs(k)):
                demote.add(k)

        def top_input(x):
            return G.nodes[x].port_dir == "in" and G.nodes[x].inst in G.tops

        for k in self.name_resets - self.async_resets:
            if top_input(k):
                continue
            drivers = [
                p
                for p, et in G.preds(k, {EdgeType.DATA, EdgeType.CONTROL, EdgeType.PORT})
                if p != k
            ]
            # a reset is driven by a top-level reset, a reset synchronizer or constants; a signal
            # computed by ordinary logic (or wired from a valid/data net) is a datapath clear
            if any(p not in resets and not top_input(p) for p in drivers):
                demote.add(k)
        for k in demote:
            for _, t, d in list(G.g.out_edges(k, data=True)):
                if d["type"] == EdgeType.RESET:
                    G.g.remove_edge(k, t, key=EdgeType.RESET.value)
                    G.add_edge(k, t, EdgeType.CONTROL, d["via"])

    def _fix_reset_clocks(self):
        """A signal that acts as a reset anywhere is never a clock: buggy-but-legal RTL such as
        `always @(posedge clk or negedge arstn) if (!brstn)` would otherwise make arstn a clock
        there (and name heuristics do not survive obfuscation)."""
        G = self.G
        resets = {s for s, _, d in G.g.edges(data=True) if d["type"] == EdgeType.RESET}
        for k in resets:
            for _, t, d in list(G.g.out_edges(k, data=True)):
                if d["type"] == EdgeType.CLOCK:
                    G.g.remove_edge(k, t, key=EdgeType.CLOCK.value)
                    G.add_edge(k, t, EdgeType.RESET, d["via"])

    def _resolve_owners(self):
        paths = sorted(self.G.instances, key=len, reverse=True)
        for n in self.G.nodes.values():
            for p in paths:
                if n.key.startswith(p + "."):
                    n.inst = p
                    n.module = self.G.instances[p].module
                    n.rel = n.key[len(p) + 1 :]
                    break


def build_graph(design: Design) -> DesignGraph:
    return _Builder(design).build()
