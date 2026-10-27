"""Deterministic FSM extraction from the elaborated AST (no LLM, no hallucination).

For every FSM-candidate state register S (and its combinational next-state twin N, if any):
  states       enum literals / parameter names / literals the register can take
  reset_state  value assigned under the reset condition
  transitions  (src, dst, condition text) from `case (S)` items, `if (S == X)` guards,
               assignments of constants to S/N and `c ? A : B` right-hand sides
  outputs      signals decoded from the state: moore (only S) or mealy (S + inputs)

Supported: one-process and two-process coding styles, enum or parameter/localparam encodings,
nested if/else and case on other signals (become conditions), trailing reset overrides.
Not supported (reported in `warnings`): one-hot `case (1'b1) state[X]` style, arithmetic next
state (`state <= state + 1`, which is a counter anyway), FSMs split across modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pyslang import ast

from .elab import Design
from .entities import EntityTable
from .graph import DesignGraph, EdgeType


@dataclass
class Transition:
    src: str  # state name or "*" (any state)
    dst: str
    cond: str  # "1" = unconditional


@dataclass
class FSM:
    module: str
    instance: str
    state: str
    next: str | None
    style: str  # one-process | two-process
    states: list[dict] = field(default_factory=list)  # {name, value}
    reset_state: str | None = None
    transitions: list[Transition] = field(default_factory=list)
    outputs: list[dict] = field(default_factory=list)  # {signal, kind}
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "module": self.module,
            "instance": self.instance,
            "state": self.state,
            "next": self.next,
            "style": self.style,
            "states": self.states,
            "reset_state": self.reset_state,
            "transitions": [t.__dict__ for t in self.transitions],
            "outputs": self.outputs,
            "warnings": self.warnings,
            "semantic_check": getattr(self, "semantic_check", None),
            **(
                {"semantic_transitions": self.semantic_transitions}
                if getattr(self, "semantic_transitions", None)
                else {}
            ),
        }

    def mermaid(self) -> str:
        lines = ["stateDiagram-v2"]
        if self.reset_state:
            lines.append(f"    [*] --> {_mid(self.reset_state)}")
        for t in self.transitions:
            srcs = ["ANY_STATE"] if t.src == "*" else [t.src]
            for s in srcs:
                if s == t.dst and t.cond == "1":
                    continue
                label = "" if t.cond == "1" else " : " + t.cond.replace(":", "∶")
                lines.append(f"    {_mid(s)} --> {_mid(t.dst)}{label}")
        for o in self.outputs:
            lines.append(f"    %% output {o['signal']} ({o['kind']})")
        return "\n".join(lines)

    def dot(self, max_label: int = 60, hide_self_loops: bool = True) -> str:
        names = [s["name"] for s in self.states]
        out = [
            f'digraph "{self.module}.{self.state}" {{',
            '  rankdir=LR; node [shape=ellipse, fontname="Helvetica", fontsize=10];',
            '  edge [fontname="Helvetica", fontsize=8];',
            f'  labelloc=t; label="{self.module}.{self.state} '
            f'({self.style}, {len(names)} states)";',
        ]
        if self.reset_state:
            out.append("  __reset [shape=point, width=0.15];")
            out.append(f'  __reset -> "{self.reset_state}" [label="reset"];')
        for n in names:
            out.append(
                f'  "{n}" [{"peripheries=2, " if n == self.reset_state else ""}label="{n}"];'
            )
        # one arrow per (src, dst); "*" (from any state) is drawn once from a pseudo node
        arrows: dict[tuple[str, str], list[str]] = {}
        for t in self.transitions:
            if hide_self_loops and t.src == t.dst:
                continue
            arrows.setdefault((t.src, t.dst), []).append("" if t.cond == "1" else t.cond)
        if any(s == "*" for s, _ in arrows):
            out.append(
                '  "__any" [label="any state", shape=box, style="rounded,dashed", '
                'color="#e76f51", fontsize=9];'
            )

        def short(c: str) -> str:
            c = c.replace('"', "'")
            return c if len(c) <= max_label else c[: max_label - 1] + "…"

        for (s, d), conds in arrows.items():
            conds = [c for c in dict.fromkeys(conds)]
            lab = (
                ""
                if "" in conds
                else " |\\n".join(short(c) for c in conds[:3])
                + (f" |\\n(+{len(conds) - 3} more)" if len(conds) > 3 else "")
            )
            src = "__any" if s == "*" else s
            style = ', style=dashed, color="#e76f51"' if s == "*" else ""
            out.append(f'  "{src}" -> "{d}" [label="{lab}"{style}];')
        if self.outputs:
            outs = ", ".join(f"{o['signal']}({o['kind']})" for o in self.outputs)
            out.append(f'  __outs [shape=note, fontsize=9, label="outputs: {outs}"];')
        out.append("}")
        return "\n".join(out)


def _mid(s: str) -> str:
    return re.sub(r"\W", "_", s)


def _text(e) -> str:
    try:
        while e is not None and e.syntax is None and isinstance(e, ast.ConversionExpression):
            e = e.operand  # implicit conversions have no syntax of their own
        return re.sub(r"\s+", " ", str(e.syntax)).strip()
    except Exception:
        return "?"


_SIMPLE = re.compile(r"^[\w.\[\]:']+$")


def _neg(c: str) -> str:
    """!c with trivial simplification: !(!x) -> x, !x for plain identifiers."""
    m = re.fullmatch(r"!\(?\s*([\w.\[\]:']+)\s*\)?", c)
    if m:
        return m.group(1)
    m = re.fullmatch(r"!\((.*)\)", c)
    if m and m.group(1).count("(") == m.group(1).count(")") and _SIMPLE.match(m.group(1)):
        return m.group(1)
    if _SIMPLE.match(c) or _wrapped(c):
        return "!" + c
    return f"!({c})"


def _wrapped(c: str) -> bool:
    """True if the whole string is one balanced (...) group."""
    if not (c.startswith("(") and c.endswith(")")):
        return False
    depth = 0
    for i, ch in enumerate(c):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and i < len(c) - 1:
            return False
    return True


def _paren(c: str) -> str:
    """Parenthesize a condition containing a top-level || before joining it with &&."""
    if "||" not in c or _wrapped(c):
        return c
    depth = 0
    for i in range(len(c) - 1):
        depth += c[i] == "("
        depth -= c[i] == ")"
        if depth == 0 and c[i : i + 2] == "||":
            return f"({c})"
    return c


def _is_xz(v: str) -> bool:
    v = v.strip().strip("()").strip()
    return bool(re.search(r"'s?[bodhBODH]?[xXzZ?_]+$", v)) or v in ("'x", "'z", "x", "z")


_LIT = re.compile(
    r"^\(?\s*(?:(\d+)\s*)?'s?([bodhBODH])\s*([0-9a-fA-F_]+)\s*\)?$|^\(?\s*(\d+)\s*\)?$"
)


def _lit_value(t: str) -> str | None:
    """Verilog literal -> decimal string (so 2'b0 and 2'b00 are the same state)."""
    m = _LIT.match(t.strip())
    if not m:
        return None
    if m.group(4) is not None:
        return str(int(m.group(4)))
    base = {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(2).lower()]
    try:
        return str(int(m.group(3).replace("_", ""), base))
    except ValueError:
        return None


def _strip(e):
    while isinstance(e, ast.ConversionExpression):
        e = e.operand
    return e


def _const_name(e) -> tuple[str, str] | None:
    """(name, value) when `e` is a constant state value: enum literal, parameter or literal."""
    e = _strip(e)
    if isinstance(e, ast.ValueExpressionBase):
        sym = e.symbol
        if isinstance(sym, ast.EnumValueSymbol):
            return sym.name, str(sym.value)
        if isinstance(sym, ast.ParameterSymbol):
            try:
                return sym.name, str(sym.value)
            except Exception:
                return sym.name, "?"
        return None
    t = _text(e)
    v = _lit_value(t)
    if v is not None:
        return v, v
    if isinstance(e, (ast.IntegerLiteral, ast.UnbasedUnsizedIntegerLiteral)):
        return t, t
    try:
        c = e.constant
        if c is not None and not e.bad:
            return t, str(c)
    except Exception:
        pass
    return None


def _find_instance(design: Design, path: str):
    for top in design.tops:
        stack = [top]
        while stack:
            s = stack.pop()
            if s.hierarchicalPath == path:
                return s
            for m in _members(s.body):
                if isinstance(m, ast.InstanceSymbol):
                    stack.append(m)
    return None


def _members(scope):
    for m in scope:
        if isinstance(m, (ast.GenerateBlockSymbol,)) and not m.isUninstantiated:
            yield from _members(m)
        elif isinstance(m, ast.GenerateBlockArraySymbol):
            for e in m.entries:
                if not e.isUninstantiated:
                    yield from _members(e)
        else:
            yield m


class _Extractor:
    def __init__(self, G: DesignGraph, S_key: str, N_key: str | None, scope=None):
        self.scope = scope
        self.G = G
        self.S = S_key
        self.N = N_key
        self.targets = {S_key} | ({N_key} if N_key else set())
        self.resets = {s for s, _, d in G.g.edges(data=True) if d["type"] == EdgeType.RESET}
        self.trans: list[Transition] = []
        self.states: dict[str, str] = {}
        self.reset_state: str | None = None
        self.warnings: list[str] = []
        self.assigns = 0

    def key(self, e) -> str | None:
        e = _strip(e)
        if isinstance(e, ast.ValueExpressionBase) and e.symbol.kind in (
            ast.SymbolKind.Variable,
            ast.SymbolKind.Net,
        ):
            return e.symbol.hierarchicalPath
        return None

    def reads(self, e) -> set[str]:
        out = set()

        def cb(n):
            if isinstance(n, ast.ValueExpressionBase) and n.symbol.kind in (
                ast.SymbolKind.Variable,
                ast.SymbolKind.Net,
            ):
                out.add(n.symbol.hierarchicalPath)
            return True

        try:
            e.visit(cb)
        except Exception:
            pass
        return out

    # ------------------------------------------------------------- constants
    def const_bool(self, e) -> bool | None:
        """Value of a condition if it is elaboration-time constant (parameters/defines),
        else None."""
        if self.scope is None:
            return None
        try:
            v = e.eval(ast.EvalContext(self.scope))
            if v is None or v.bad if hasattr(v, "bad") else False:
                return None
            if str(v) in ("<unset>", "") or v.hasUnknown():
                return None
            return bool(v.isTrue())
        except Exception:
            return None

    def cond(self, e) -> tuple[bool | None, str]:
        """(constant value or None, simplified text): drops constant-true conjuncts of && chains and
        constant-false disjuncts of || chains, so parameter-disabled logic disappears from
        labels."""
        c = self.const_bool(e)
        if c is not None:
            return c, "1" if c else "0"
        e2 = _strip(e)
        if isinstance(e2, ast.BinaryExpression):
            op = str(e2.op).split(".")[-1]
            if op in ("LogicalAnd", "LogicalOr"):
                lv, lt = self.cond(e2.left)
                rv, rt = self.cond(e2.right)
                if op == "LogicalAnd":
                    if lv is False or rv is False:
                        return False, "0"
                    parts = [t for v, t in ((lv, lt), (rv, rt)) if v is not True]
                    return (True, "1") if not parts else (None, " && ".join(parts))
                if lv is True or rv is True:
                    return True, "1"
                parts = [t for v, t in ((lv, lt), (rv, rt)) if v is not False]
                return (
                    (False, "0")
                    if not parts
                    else (None, "(" + " || ".join(parts) + ")" if len(parts) > 1 else parts[0])
                )
        return None, _text(e)

    # ------------------------------------------------------------------ walk
    def stmt(self, st, src: frozenset | None, conds: tuple, in_reset: bool):
        if st is None:
            return
        if isinstance(st, ast.BlockStatement):
            return self.stmt(st.body, src, conds, in_reset)
        if isinstance(st, ast.TimedStatement):
            return self.stmt(st.stmt, src, conds, in_reset)
        if isinstance(st, ast.StatementList):
            for x in st.list:
                self.stmt(x, src, conds, in_reset)
            return
        if isinstance(st, ast.ConditionalStatement):
            c = st.conditions[0].expr
            cv, ct = self.cond(c)
            if cv is True:  # parameter-enabled: only the taken branch exists
                return self.stmt(st.ifTrue, src, conds, in_reset)
            if cv is False:  # parameter-disabled branch is dead logic
                return self.stmt(st.ifFalse, src, conds, in_reset)
            rd = self.reads(c)
            st_val = self._state_test(c)
            if rd and rd <= self.resets:
                self.stmt(st.ifTrue, src, conds, True)
                self.stmt(st.ifFalse, src, conds, in_reset)
            elif st_val is not None:
                self.stmt(st.ifTrue, frozenset({st_val}), conds, in_reset)
                self.stmt(st.ifFalse, src, conds + (_neg(_text(c)),), in_reset)
            else:
                self.stmt(st.ifTrue, src, conds + (ct,), in_reset)
                self.stmt(st.ifFalse, src, conds + (_neg(ct),), in_reset)
            return
        if isinstance(st, ast.CaseStatement):
            on_state = (
                self.key(st.expr) in self.targets - ({self.N} if self.N else set())
                or self.key(st.expr) == self.S
            )
            if self._is_onehot_case(st):
                self.warnings.append("one-hot `case (1'b1)` style not extracted")
                return
            covered: set[str] = set()
            for it in st.items:
                if on_state:
                    vals = []
                    for x in it.expressions:
                        cn = _const_name(x)
                        if cn:
                            self.states.setdefault(cn[0], cn[1])
                            vals.append(cn[0])
                    covered |= set(vals)
                    self.stmt(it.stmt, frozenset(vals) if vals else src, conds, in_reset)
                else:
                    sel_one = self.const_bool(st.expr) is True  # case (1'b1): priority select
                    items = []
                    for x in it.expressions:
                        if sel_one:
                            v, t = self.cond(x)
                            if v is False:
                                continue
                            items.append(t)
                        else:
                            items.append(f"{_text(st.expr)} == {_text(x)}")
                    if not items:
                        continue  # every label of this item is parameter-disabled
                    lab = " || ".join(items)
                    self.stmt(it.stmt, src, conds + (lab,), in_reset)
            if st.defaultCase is not None:
                if on_state:
                    self.stmt(
                        st.defaultCase,
                        frozenset({"__default__:" + ",".join(sorted(covered))}),
                        conds,
                        in_reset,
                    )
                else:
                    self.stmt(st.defaultCase, src, conds + ("else",), in_reset)
            return
        if isinstance(st, (ast.ForLoopStatement, ast.ForeachLoopStatement, ast.WhileLoopStatement)):
            return self.stmt(st.body, src, conds, in_reset)
        if isinstance(st, ast.ExpressionStatement) and isinstance(
            st.expr, ast.AssignmentExpression
        ):
            a = st.expr
            if self.key(a.left) in self.targets:
                self.assign(a.right, src, conds, in_reset)
            return

    def _is_onehot_case(self, st) -> bool:
        e = _strip(st.expr)
        return _const_name(e) is not None and any(
            self.S in self.reads(x) for it in st.items for x in it.expressions
        )

    def _state_test(self, c) -> str | None:
        """`S == X` (or `X == S`) -> X."""
        c = _strip(c)
        if isinstance(c, ast.BinaryExpression) and str(c.op).split(".")[-1] in (
            "Equality",
            "CaseEquality",
        ):
            for a, b in ((c.left, c.right), (c.right, c.left)):
                if self.key(a) == self.S:
                    cn = _const_name(b)
                    if cn:
                        self.states.setdefault(cn[0], cn[1])
                        return cn[0]
        return None

    def assign(self, rhs, src, conds, in_reset):
        self.assigns += 1
        r = _strip(rhs)
        if isinstance(r, ast.ConditionalExpression):
            c = _text(r.conditions[0].expr)
            self.assign(r.left, src, conds + (c,), in_reset)
            self.assign(r.right, src, conds + (_neg(c),), in_reset)
            return
        k = self.key(r)
        if k in self.targets:  # hold (S <= S / N = S) or register update (S <= N)
            return
        cn = _const_name(r)
        if cn is None:
            self.warnings.append(f"non-constant next state: {_text(rhs)}")
            return
        if _is_xz(cn[0]) or _is_xz(cn[1]):
            return  # don't-care default (`state <= 'x`), not a real state
        self.states.setdefault(cn[0], cn[1])
        if in_reset:
            self.reset_state = cn[0]
            return
        uniq = list(dict.fromkeys(conds))  # `else && else` -> `else`
        cond = " && ".join(_paren(c) for c in uniq) if uniq else "1"
        for s in sorted(src) if src else ["*"]:
            self.trans.append(Transition(src=s, dst=cn[0], cond=cond))


def _comb_from_input(G: DesignGraph, k: str, skip: set[str], depth: int = 4) -> bool:
    seen, frontier = {k}, [k]
    for _ in range(depth):
        nxt = []
        for x in frontier:
            for p, et in G.preds(x):
                if et in (EdgeType.CLOCK, EdgeType.RESET) or p in seen or p in skip:
                    continue
                pn = G.nodes[p]
                if pn.port_dir == "in":
                    return True
                if not pn.is_state:
                    seen.add(p)
                    nxt.append(p)
        frontier = nxt
    return False


def _scan_blocks(inst, ex: _Extractor):
    for m in _members(inst.body):
        if isinstance(m, ast.ProceduralBlockSymbol):
            if m.procedureKind in (ast.ProceduralBlockKind.Initial, ast.ProceduralBlockKind.Final):
                continue
            ex.stmt(m.body, None, (), False)
        elif isinstance(m, ast.ContinuousAssignSymbol):
            a = m.assignment
            if isinstance(a, ast.AssignmentExpression) and ex.key(a.left) in ex.targets:
                ex.assign(a.right, None, (), False)


def _expand_default(ex: _Extractor) -> None:
    """`default:` of a case on the state = every state not listed explicitly."""
    names = list(ex.states)
    out = [t for t in ex.trans if not t.src.startswith("__default__")]
    for t in ex.trans:
        if t.src.startswith("__default__"):
            covered = set(filter(None, t.src.split(":", 1)[1].split(",")))
            for s in names:
                if s not in covered:  # default only reaches values not listed as case items
                    out.append(Transition(src=s, dst=t.dst, cond=t.cond))
    # dedupe
    seen, uniq = set(), []
    for t in out:
        k = (t.src, t.dst, t.cond)
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    ex.trans = uniq


def extract_fsms(
    design: Design,
    G: DesignGraph,
    tables: list[EntityTable],
    extra_state_ids: dict[str, set[str]] | None = None,
) -> list[FSM]:
    """FSMs of every module (canonical instance). `extra_state_ids`: module -> entity ids the
    teacher labeled FSM_STATE that the frontend did not flag."""
    out: list[FSM] = []
    for t in tables:
        ids = {r.id for r in t.rows if r.fsm_candidate} | set(
            (extra_state_ids or {}).get(t.module, set())
        )
        if not ids:
            continue
        inst = _find_instance(design, t.canonical_instance)
        if inst is None:
            continue
        rows = t.by_id()
        for eid in sorted(ids, key=lambda x: int(x[1:])):
            row = rows.get(eid)
            if row is None or row.kind == "inst":
                continue
            S = row.members[0] if row.members else f"{t.canonical_instance}.{row.name}"
            if S not in G.nodes:
                continue
            # next-state twin: combinational DATA predecessor that is itself controlled by S
            N = None
            for p, _ in G.preds(S, {EdgeType.DATA}):
                pn = G.nodes[p]
                if (
                    p != S
                    and not pn.is_state
                    and any(q == S for q, _ in G.preds(p, {EdgeType.CONTROL}))
                ):
                    N = p
                    break
            ex = _Extractor(G, S, N, scope=inst.body)
            for v in G.nodes[S].enum_values:
                ex.states.setdefault(v, "")
            _scan_blocks(inst, ex)
            _expand_default(ex)
            # Moore / Mealy outputs: nodes driven from S (or N) in this instance
            outs = []
            for k, n in G.nodes.items():
                if n.inst != t.canonical_instance or k in ex.targets:
                    continue
                preds = {
                    p for p, et in G.preds(k) if et not in (EdgeType.CLOCK, EdgeType.RESET)
                } - {k}
                if S not in preds:
                    continue
                is_port = n.port_dir == "out"
                pure_decode = not n.is_state and preds <= {
                    S
                }  # e.g. `assign busy = (state != IDLE)`
                if not (is_port or pure_decode):
                    continue  # datapath logic that merely *uses* the state is not an FSM output
                # Mealy = a combinational path from an input port (not through a register)
                kind = (
                    "mealy" if (not n.is_state and _comb_from_input(G, k, ex.targets)) else "moore"
                )
                outs.append({"signal": n.name, "kind": kind, "port": is_port})
            fsm = FSM(
                module=t.module,
                instance=t.canonical_instance,
                state=row.name,
                next=G.nodes[N].name if N else None,
                style="two-process" if N else "one-process",
                states=[{"name": k, "value": v} for k, v in ex.states.items()],
                reset_state=ex.reset_state,
                transitions=ex.trans,
                outputs=sorted(outs, key=lambda o: (not o["port"], o["signal"])),
                warnings=sorted(set(ex.warnings)),
            )
            if not fsm.transitions:
                fsm.warnings.append("no transitions extracted")
            out.append(fsm)
    return out
