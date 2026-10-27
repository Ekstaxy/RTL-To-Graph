"""e8 lines: source lines for FSM transitions, the reset assignment and one-hot bit indices.

Library module (no CLI), loaded by e8_extract.py / candidates.py:

    uv run --package rtl2d-l1 python layers/l1_extract/experiments/e8_fsm_extra/e8_extract.py ...

`LineWalker` subclasses rtl2d_l1.frontend.fsm._Extractor, so it walks the slang AST with exactly
the same `stmt`/`assign` visitors as L1 and only *records* where each constant state assignment
sits (file, line via the slang SourceManager; macro uses are mapped to the use site). Two modes:

* exact ("l1"): L1's behaviour unchanged; used for syntactically extracted FSMs, so the recorded
  (src, dst, cond) set must equal L1's transitions (checked by e8_extract, mismatch logged).
* extended ("ext"): for semantic-only and counter FSMs. Adds what fsm.py skips: one-hot bit tests
  (`if (s[K])`, `case (1'b1) s[K]:`), state tests on port aliases of the register, next-state logic
  in a submodule, relative updates `s <= s +/- k`, and keeps the condition expressions so a record
  can be checked against a concrete state value (`applies`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pyslang import ast

from rtl2d_l1.frontend import fsm as l1fsm
from rtl2d_l1.frontend.fsm_semantic import Unsupported, _cv_int, _lroots, _mask, _parse_const
from rtl2d_l1.frontend.graph import EdgeType


@dataclass
class Rec:
    """One constant (or relative) assignment to the state register."""

    src: str  # state name | "*" | "__default__:<covered,...>" | "__bit:<K>"
    dst: str | None  # constant name (None for a relative update)
    dst_value: int | None
    cond: str
    file: str
    line: int
    in_reset: bool = False
    rel: int | None = None  # s <= s + rel (mod 2**w), extended mode only
    conds: tuple = ()  # the individual condition texts joined into `cond`
    guards: tuple = ()  # (expr, polarity, text) of enclosing if / ?: conditions
    lhs: str | None = None  # key of the assigned target (procedural assignments)
    after: tuple = ()  # statements that run after this one in the same procedural block
    wline: tuple = ()  # (file, line) of the enclosing assignment statement


@dataclass
class WalkResult:
    recs: list[Rec] = field(default_factory=list)
    writes: list[dict] = field(default_factory=list)  # every assignment to a target {file,line,..}
    states: dict[str, str] = field(default_factory=dict)  # constant name -> value text
    warnings: list[str] = field(default_factory=list)
    wires: dict[str, object] = field(default_factory=dict)  # net key -> defining expression


def src_line(design, node) -> dict | None:
    """{file, line} of an AST node; macro expansions map to the line of the macro use."""
    try:
        loc = node.sourceRange.start
    except Exception:
        return None
    sm = design.sm
    try:
        if sm.isMacroLoc(loc):
            loc = sm.getFullyExpandedLoc(loc)
        line = int(sm.getLineNumber(loc))
    except Exception:
        return None
    return {"file": design.file_of(loc), "line": line} if line else None


def const_int(e) -> int | None:
    """Integer value of an elaboration-time constant expression (literal / parameter)."""
    e = l1fsm._strip(e)
    if isinstance(e, ast.ValueExpressionBase) and isinstance(
        e.symbol, (ast.ParameterSymbol, ast.EnumValueSymbol)
    ):
        try:
            return _cv_int(e.symbol.value)[0]
        except Exception:
            return None
    try:
        c = e.constant
        return _cv_int(c)[0] if c is not None else None
    except Exception:
        return None


def value_of(text: str | None) -> int | None:
    if not text:
        return None
    try:
        return _parse_const(text)[0]
    except Unsupported:
        return None


def _op(e) -> str:
    return str(e.op).split(".")[-1]


class LineWalker(l1fsm._Extractor):
    def __init__(self, design, G, S, N, scope, *, ext=False, reads=(), writes=(), relative=False):
        super().__init__(G, S, N, scope=scope)
        self.design = design
        self.ext = ext
        self.relative = relative
        self.width = G.nodes[S].width or 1
        self.read_keys = {S} | set(reads)
        if ext:
            self.targets = {S} | set(writes) | set(reads)
        self.res = WalkResult(states=self.states, warnings=self.warnings)
        self._stmt = None
        self._guards: tuple = ()
        self._lhs: str | None = None
        self._after: tuple = ()

    # ----------------------------------------------------------------- recording
    def _loc(self, node) -> dict:
        return src_line(self.design, node) or src_line(self.design, self._stmt) or {
            "file": "", "line": 0}

    def _wline(self) -> tuple:
        loc = src_line(self.design, self._stmt) if self._stmt is not None else None
        return (loc["file"], loc["line"]) if loc else ()

    def note_write(self, node, lhs, in_reset: bool) -> None:
        if set(_lroots(lhs)) & self.targets:
            loc = src_line(self.design, node)
            if loc:
                whole = self.key(lhs) is not None
                self.res.writes.append({**loc, "in_reset": in_reset, "bitwise": not whole})

    def stmt(self, st, src, conds, in_reset):
        if isinstance(st, ast.StatementList):  # same order as fsm.py; remembers what follows
            a0, items = self._after, list(st.list)
            for i, x in enumerate(items):
                self._after = tuple(items[i + 1:]) + a0
                self.stmt(x, src, conds, in_reset)
            self._after = a0
            return
        if isinstance(st, ast.ExpressionStatement) and isinstance(
            st.expr, ast.AssignmentExpression
        ):
            self._stmt = st
            self._lhs = self.key(st.expr.left)
            self.note_write(st, st.expr.left, in_reset)
        if isinstance(st, ast.ConditionalStatement):
            return (self._if if self.ext else self._if_exact)(st, src, conds, in_reset)
        if self.ext and isinstance(st, ast.CaseStatement) and self._is_onehot_case(st):
            return self._onehot_case(st, src, conds, in_reset)
        return super().stmt(st, src, conds, in_reset)

    def assign(self, rhs, src, conds, in_reset):
        r = l1fsm._strip(rhs)
        if isinstance(r, ast.ConditionalExpression):  # as fsm.py, plus the guard expressions
            self.assigns += 1
            ce = r.conditions[0].expr
            c = l1fsm._text(ce)
            nc = l1fsm._neg(c)
            g0 = self._guards
            self._guards = g0 + ((ce, True, c),)
            self.assign(r.left, src, conds + (c,), in_reset)
            self._guards = g0 + ((ce, False, nc),)
            self.assign(r.right, src, conds + (nc,), in_reset)
            self._guards = g0
            return
        loc = self._loc(r)
        if self.relative and not in_reset:
            rel = self._relative(r)
            if rel is not None:
                self.assigns += 1
                self._add(src, None, None, conds, loc, rel=rel)
                return
        n0 = len(self.trans)
        super().assign(rhs, src, conds, in_reset)
        cn = l1fsm._const_name(r)
        if cn is None or l1fsm._is_xz(cn[0]) or l1fsm._is_xz(cn[1]):
            return
        if in_reset:
            self.res.recs.append(Rec("*", cn[0], value_of(cn[1]), "reset", loc["file"],
                                     loc["line"], in_reset=True, guards=self._guards,
                                     lhs=self._lhs, after=self._after, wline=self._wline()))
            return
        for t in self.trans[n0:]:
            self.res.recs.append(Rec(t.src, t.dst, value_of(self.states.get(t.dst)), t.cond,
                                     loc["file"], loc["line"], conds=tuple(dict.fromkeys(conds)),
                                     guards=self._guards, lhs=self._lhs, after=self._after,
                                     wline=self._wline()))

    def _add(self, src, dst, dval, conds, loc, rel=None):
        uniq = list(dict.fromkeys(conds))
        cond = " && ".join(l1fsm._paren(c) for c in uniq) if uniq else "1"
        for s in sorted(src) if src else ["*"]:
            self.res.recs.append(Rec(s, dst, dval, cond, loc["file"], loc["line"], rel=rel,
                                     conds=tuple(uniq), guards=self._guards, lhs=self._lhs,
                                     after=self._after, wline=self._wline()))

    def _relative(self, r) -> int | None:
        """`s + k` / `s - k` / `k + s` -> k (mod 2**w)."""
        if not isinstance(r, ast.BinaryExpression) or _op(r) not in ("Add", "Subtract"):
            return None
        a, b = r.left, r.right
        if self.key(a) in self.read_keys and const_int(b) is not None:
            k = const_int(b)
            return (k if _op(r) == "Add" else -k) & _mask(self.width)
        if _op(r) == "Add" and self.key(b) in self.read_keys and const_int(a) is not None:
            return const_int(a) & _mask(self.width)
        return None

    # ------------------------------------------------------- extended-mode visitors
    def _state_test(self, c):
        if not self.ext:
            return super()._state_test(c)
        c = l1fsm._strip(c)
        if isinstance(c, ast.BinaryExpression) and _op(c) in ("Equality", "CaseEquality"):
            for a, b in ((c.left, c.right), (c.right, c.left)):
                if self.key(a) in self.read_keys:
                    cn = l1fsm._const_name(b)
                    if cn:
                        self.states.setdefault(cn[0], cn[1])
                        return cn[0]
        return None

    def _is_onehot_case(self, st) -> bool:
        e = l1fsm._strip(st.expr)
        return l1fsm._const_name(e) is not None and any(
            self.reads(x) & self.read_keys for it in st.items for x in it.expressions
        )

    def bits(self, c) -> set[int] | None:
        """Bit indices K of a one-hot test `s[K]`, `s[K] == 1`, `s[A] | s[B]`; else None."""
        c = l1fsm._strip(c)
        if isinstance(c, ast.ElementSelectExpression) and self.key(c.value) in self.read_keys:
            k = const_int(c.selector)
            return {k} if k is not None and self.G.nodes[self.S].width > 1 else None
        if isinstance(c, ast.BinaryExpression):
            if _op(c) in ("BinaryOr", "LogicalOr"):
                a, b = self.bits(c.left), self.bits(c.right)
                return a | b if a and b else None
            if _op(c) in ("Equality", "CaseEquality"):
                for a, b in ((c.left, c.right), (c.right, c.left)):
                    if const_int(b) == 1 and self.bits(a):
                        return self.bits(a)
        return None

    def _conjuncts(self, c) -> list:
        c2 = l1fsm._strip(c)
        if isinstance(c2, ast.BinaryExpression) and _op(c2) in ("LogicalAnd", "BinaryAnd"):
            try:
                one_bit = _op(c2) == "LogicalAnd" or c2.type.bitWidth == 1
            except Exception:
                one_bit = False
            if one_bit:
                return self._conjuncts(c2.left) + self._conjuncts(c2.right)
        return [c]

    def _if_exact(self, st, src, conds, in_reset):
        """fsm._Extractor.stmt's ConditionalStatement branch, verbatim, plus guard tracking."""
        c = st.conditions[0].expr
        cv, ct = self.cond(c)
        if cv is True:
            return self.stmt(st.ifTrue, src, conds, in_reset)
        if cv is False:
            return self.stmt(st.ifFalse, src, conds, in_reset)
        rd = self.reads(c)
        st_val = self._state_test(c)
        g0 = self._guards
        if rd and rd <= self.resets:
            self.stmt(st.ifTrue, src, conds, True)
            self.stmt(st.ifFalse, src, conds, in_reset)
            return
        if st_val is not None:
            t_src, t_conds, nt = frozenset({st_val}), conds, l1fsm._neg(l1fsm._text(c))
        else:
            t_src, t_conds, nt = src, conds + (ct,), l1fsm._neg(ct)
        self._guards = g0 + ((c, True, ct),)
        self.stmt(st.ifTrue, t_src, t_conds, in_reset)
        self._guards = g0 + ((c, False, nt),)
        self.stmt(st.ifFalse, src, conds + (nt,), in_reset)
        self._guards = g0

    def _if(self, st, src, conds, in_reset):
        c = st.conditions[0].expr
        cv, ct = self.cond(c)
        if cv is True:
            return self.stmt(st.ifTrue, src, conds, in_reset)
        if cv is False:
            return self.stmt(st.ifFalse, src, conds, in_reset)
        rd = self.reads(c)
        g0 = self._guards
        if rd and rd <= self.resets:
            self.stmt(st.ifTrue, src, conds, True)
            self.stmt(st.ifFalse, src, conds, in_reset)
            return
        st_val = self._state_test(c)
        parts = self._conjuncts(c)
        bit_parts = [(p, self.bits(p)) for p in parts]
        hot = [b for _, b in bit_parts if b]
        if st_val is not None:
            t_src, t_conds = frozenset({st_val}), conds
        elif len(hot) == 1:
            t_src = frozenset(f"__bit:{k}" for k in hot[0])
            t_conds = conds + tuple(l1fsm._text(p) for p, b in bit_parts if not b)
        else:
            t_src, t_conds = src, conds + (ct,)
        self._guards = g0 + ((c, True, ct),)
        self.stmt(st.ifTrue, t_src, t_conds, in_reset)
        nt = l1fsm._neg(l1fsm._text(c) if t_src is not src else ct)
        self._guards = g0 + ((c, False, nt),)
        self.stmt(st.ifFalse, src, conds + (nt,), in_reset)
        self._guards = g0

    def _onehot_case(self, st, src, conds, in_reset):
        covered: set[int] = set()
        for it in st.items:
            ks: set[int] = set()
            for x in it.expressions:
                ks |= self.bits(x) or set()
            covered |= ks
            s2 = frozenset(f"__bit:{k}" for k in ks) if ks else src
            self.stmt(it.stmt, s2, conds, in_reset)
        if st.defaultCase is not None:
            # `default:` of `case (1'b1)` runs only when none of the tested bits is set
            s2 = (frozenset({"__nobit:" + ",".join(map(str, sorted(covered)))})
                  if covered and src is None else src)
            self.stmt(st.defaultCase, s2, conds + ("else",), in_reset)


# ---------------------------------------------------------------------- driving
def scan(inst, w: LineWalker) -> None:
    """fsm._scan_blocks with line capture for continuous assignments; also collects the
    defining expression of every net (`assign x = e;`, `wire x = e;`) for guard evaluation."""
    for m in l1fsm._members(inst.body):
        if isinstance(m, ast.ProceduralBlockSymbol):
            if m.procedureKind in (ast.ProceduralBlockKind.Initial, ast.ProceduralBlockKind.Final):
                continue
            w._after, w._guards = (), ()
            w.stmt(m.body, None, (), False)
        elif isinstance(m, ast.ContinuousAssignSymbol):
            a = m.assignment
            if isinstance(a, ast.AssignmentExpression):
                w._stmt, w._lhs, w._after, w._guards = a, w.key(a.left), (), ()
                if w._lhs:
                    w.res.wires.setdefault(w._lhs, a.right)
                w.note_write(a, a.left, False)
                if w.key(a.left) in w.targets:
                    w.assign(a.right, None, (), False)
        elif isinstance(m, ast.NetSymbol) and m.initializer is not None:
            w.res.wires.setdefault(m.hierarchicalPath, m.initializer)


def next_twin(G, S: str) -> str | None:
    """L1's next-state twin rule (fsm.extract_fsms): combinational DATA pred controlled by S."""
    for p, _ in G.preds(S, {EdgeType.DATA}):
        pn = G.nodes[p]
        if p != S and not pn.is_state and any(
            q == S for q, _ in G.preds(p, {EdgeType.CONTROL})
        ):
            return p
    return None


def aliases(G, S: str) -> set[str]:
    """Port-connected aliases of the register (same signal seen from another instance)."""
    out, stack = {S}, [S]
    while stack:
        x = stack.pop()
        for nb, _ in G.succs(x, {EdgeType.PORT}) + G.preds(x, {EdgeType.PORT}):
            if nb not in out:
                out.add(nb)
                stack.append(nb)
    return out - {S}


def next_chain(G, S: str, depth: int = 4) -> set[str]:
    """Same-width combinational nodes feeding S through DATA/PORT edges (next-state wires, also
    across instance ports)."""
    w = G.nodes[S].width
    out, frontier = set(), [S]
    for _ in range(depth):
        nxt = []
        for x in frontier:
            for p, _ in G.preds(x, {EdgeType.DATA, EdgeType.PORT}):
                pn = G.nodes[p]
                if p in out or p == S or pn.is_state or pn.width != w:
                    continue
                if pn.port_dir == "in" and pn.inst in G.tops:
                    continue
                out.add(p)
                nxt.append(p)
        frontier = nxt
    return out


def walk_exact(design, G, S: str, enum_values) -> WalkResult:
    """Exactly L1's walk for a syntactic FSM (same S, N, scope and seeding)."""
    inst = l1fsm._find_instance(design, G.nodes[S].inst)
    w = LineWalker(design, G, S, next_twin(G, S), inst.body if inst else None)
    for v in enum_values:
        w.states.setdefault(v, "")
    if inst is not None:
        scan(inst, w)
    return w.res


def walk_ext(design, G, S: str, *, relative: bool = False) -> tuple[WalkResult, set[str]]:
    """Extended walk over every instance holding the register, its aliases or its next-state
    wires. Returns the result and the set of read keys (register + aliases)."""
    reads = aliases(G, S)
    writes = next_chain(G, S)
    res = WalkResult()
    insts = sorted({G.nodes[k].inst for k in {S} | reads | writes})
    for path in insts:
        inst = l1fsm._find_instance(design, path)
        if inst is None:
            continue
        w = LineWalker(design, G, S, None, inst.body, ext=True, reads=reads, writes=writes,
                       relative=relative)
        w.states.update(res.states)
        scan(inst, w)
        res.recs += w.res.recs
        res.writes += w.res.writes
        res.states.update(w.states)
        res.warnings += w.warnings
        res.wires.update(w.res.wires)
    return res, {S} | reads


# ------------------------------------------------------------ record application
def inactive_reset(r) -> dict:
    """{reset key: inactive level} of a SemanticFSM, {} when no reset was found."""
    if r is not None and r.reset_signal is not None and r.reset_level is not None:
        return {r.reset_signal: 1 - r.reset_level}
    return {}


def resolve(name: str, states: dict[str, str], cmap: dict[str, int]) -> int | None:
    if name.startswith("__bit:"):
        return 1 << int(name.split(":", 1)[1])
    v = value_of(states.get(name))
    return v if v is not None else cmap.get(name)


def src_matches(rec: Rec, s: int, states: dict, cmap: dict, width: int) -> bool:
    if rec.src == "*":
        return True
    if rec.src.startswith("__bit:"):  # `s[K]` test: any value with bit K set
        return (s >> int(rec.src.split(":", 1)[1])) & 1 == 1
    if rec.src.startswith("__nobit:"):  # default of `case (1'b1)`: no tested bit set
        ks = [int(x) for x in rec.src.split(":", 1)[1].split(",") if x]
        return all((s >> k) & 1 == 0 for k in ks)
    if rec.src.startswith("__default__"):
        covered = [x for x in rec.src.split(":", 1)[1].split(",") if x]
        vals = {resolve(x, states, cmap) for x in covered}
        return s not in {v & _mask(width) for v in vals if v is not None}
    v = resolve(rec.src, states, cmap)
    return v is not None and v & _mask(width) == s


def state_only(G, keys: set[str], read_keys: set[str], memo: dict) -> bool:
    """True if every signal in `keys` is the register (or an alias) or combinational logic fed
    only by it and constants (e.g. `assign tick = (cnt == 15)`)."""
    for k in keys:
        if k in read_keys:
            continue
        if k not in memo:
            memo[k] = None  # cycle guard
            n = G.nodes.get(k)
            ok = n is not None and not n.is_state and not (n.port_dir == "in" and n.inst in G.tops)
            if ok:
                preds = {p for p, et in G.preds(k) if et not in (EdgeType.CLOCK, EdgeType.RESET)}
                ok = bool(preds) and state_only(G, preds, read_keys, memo)
            memo[k] = ok
        if not memo[k]:
            return False
    return True


def _and_parts(e) -> list:
    e2 = l1fsm._strip(e)
    if isinstance(e2, ast.BinaryExpression) and _op(e2) == "LogicalAnd":
        return _and_parts(e2.left) + _and_parts(e2.right)
    return [e]


@dataclass
class Ctx:
    """Evaluation context at one state value: Machine, env (register + known signals), wire
    definitions to inline, graph for the state-only test."""

    M: object
    env: dict
    leaves: set
    G: object = None
    memo: dict = field(default_factory=dict)
    wires: dict = field(default_factory=dict)


def make_ctx(s: int, M, read_keys, G=None, memo=None, known=None, wires=None) -> Ctx:
    known = known or {}
    return Ctx(M, {**{k: s for k in read_keys}, **known}, set(read_keys) | set(known), G,
               {} if memo is None else memo, wires or {})


def _one_bit(e) -> bool:
    try:
        return e.type.bitWidth == 1
    except Exception:
        return False


def tv(e, ctx: Ctx, depth: int = 0) -> bool | None:
    """Three-valued truth of `e` at the context's state: True / False when it follows from the
    register (and known signals) alone, after inlining net definitions through `&&`, `||`,
    `!`, 1-bit `&`/`|`/`~`; None when it depends on other signals."""
    e = l1fsm._strip(e)
    v = _state_value(e, ctx)
    if v is not None or depth > 8:
        return v
    if isinstance(e, ast.ValueExpressionBase):
        d = ctx.wires.get(getattr(e.symbol, "hierarchicalPath", None))
        return tv(d, ctx, depth + 1) if d is not None and _one_bit(e) else None
    if isinstance(e, ast.UnaryExpression) and (
        _op(e) == "LogicalNot" or (_op(e) == "BitwiseNot" and _one_bit(e.operand))
    ):
        x = tv(e.operand, ctx, depth + 1)
        return None if x is None else not x
    if isinstance(e, ast.BinaryExpression):
        op = _op(e)
        if op in ("BinaryAnd", "BinaryOr") and not _one_bit(e):
            return None
        if op in ("LogicalAnd", "BinaryAnd", "LogicalOr", "BinaryOr"):
            a, b = tv(e.left, ctx, depth + 1), tv(e.right, ctx, depth + 1)
            dom = op.endswith("Or")  # the value that decides the result on its own
            if a is dom or b is dom:
                return dom
            return None if a is None or b is None else not dom
    return None


def guards_hold(rec: Rec, s: int, M, read_keys: set[str], G=None, memo: dict | None = None,
                known: dict | None = None, wires: dict | None = None
                ) -> tuple[bool, dict[str, str]]:
    """Evaluate, at state value `s`, the `&&`-conjuncts of every enclosing condition whose truth
    follows from the state register alone (three-valued, with net definitions inlined, so
    `park = !(tk_live || ph_live)` is false whenever `ph_live` is) and from `known` signals
    held at a constant (the reset at its inactive level).
    Returns (record can fire in state s, {condition text: simplified text, '' = drop})."""
    repl: dict[str, str] = {}
    ctx = make_ctx(s, M, read_keys, G, memo, known, wires)
    for expr, pol, text in rec.guards:
        fixed, free = [], []
        for part in _and_parts(expr):
            v = tv(part, ctx)
            (free if v is None else fixed).append((part, v))
        if not fixed:
            continue
        all_true = all(v for _, v in fixed)
        rest = " && ".join(l1fsm._paren(l1fsm._text(p)) for p, _ in free)
        if pol and not all_true:
            return False, repl
        if not pol and all_true and not free:
            return False, repl
        if pol:
            repl[text] = rest
        else:
            repl[text] = "" if not all_true else l1fsm._neg(rest)
    return True, repl


def _state_value(e, ctx: Ctx) -> bool | None:
    try:
        rd = _reads(e)
    except Exception:
        return None
    if rd and not rd <= ctx.leaves and (
        ctx.G is None or not state_only(ctx.G, rd, ctx.leaves, ctx.memo)
    ):
        return None
    try:
        ctx.M.new_cycle(dict(ctx.env))
        return bool(ctx.M.ev(e))
    except Exception:
        return None


def definite(st, lhs: str, s: int, ctx: Ctx, read_keys, width: int, depth: int = 0) -> bool:
    """True if statement `st` surely assigns the whole of `lhs` when the register holds `s`
    (branches decided by `tv`; an undecided `if` needs both arms; a `case` on the register picks
    its item, other `case`s need every item and a default). False when unsure."""
    if st is None or depth > 32:
        return False

    def rec(x):
        return definite(x, lhs, s, ctx, read_keys, width, depth + 1)

    if isinstance(st, ast.BlockStatement):
        return rec(st.body)
    if isinstance(st, ast.TimedStatement):
        return rec(st.stmt)
    if isinstance(st, ast.StatementList):
        return any(rec(x) for x in st.list)
    if isinstance(st, ast.ExpressionStatement):
        a = st.expr
        if isinstance(a, ast.AssignmentExpression):
            k = l1fsm._strip(a.left)
            return isinstance(k, ast.ValueExpressionBase) and getattr(
                k.symbol, "hierarchicalPath", None) == lhs
        return False
    if isinstance(st, ast.ConditionalStatement):
        v = tv(st.conditions[0].expr, ctx)
        if v is not None:
            return rec(st.ifTrue if v else st.ifFalse)
        return rec(st.ifTrue) and rec(st.ifFalse)
    if isinstance(st, ast.CaseStatement):
        return _definite_case(st, s, ctx, read_keys, width, rec)
    return False


def _definite_case(st, s, ctx, read_keys, width, rec) -> bool:
    e = l1fsm._strip(st.expr)
    on_state = isinstance(e, ast.ValueExpressionBase) and getattr(
        e.symbol, "hierarchicalPath", None) in read_keys
    if on_state:
        for it in st.items:
            vals = [const_int(x) for x in it.expressions]
            if any(v is not None and v & _mask(width) == s for v in vals):
                return rec(it.stmt)
            if any(v is None for v in vals):
                return False
        return rec(st.defaultCase)
    if const_int(e) is not None:  # case (1'b1): first item whose label is true
        for it in st.items:
            vs = [tv(x, ctx) for x in it.expressions]
            if any(v is True for v in vs):
                return rec(it.stmt)
            if any(v is None for v in vs):
                return False
        return rec(st.defaultCase)
    return st.defaultCase is not None and rec(st.defaultCase) and all(
        rec(it.stmt) for it in st.items)


def overwritten(rec: Rec, s: int, ctx: Ctx, read_keys, width: int) -> bool:
    """A later statement of the same procedural block surely re-assigns the record's target
    in state s (a default like `nx = IDLE;` followed by an exhaustive `case`)."""
    return bool(rec.lhs) and any(
        definite(st, rec.lhs, s, ctx, read_keys, width) for st in rec.after)


def _reads(e) -> set[str]:
    out: set[str] = set()

    def cb(n):
        if isinstance(n, ast.ValueExpressionBase) and n.symbol.kind in (
            ast.SymbolKind.Variable, ast.SymbolKind.Net,
        ):
            out.add(n.symbol.hierarchicalPath)
        return True

    e.visit(cb)
    return out


def rec_dst(r: Rec, s: int, width: int, states, cmap) -> int | None:
    """Destination value of a record taken in state s (relative updates resolved)."""
    m = _mask(width)
    if r.rel is not None:
        return (s + r.rel) & m
    if r.dst_value is not None:
        return r.dst_value & m
    v = resolve(r.dst, states, cmap) if r.dst else None
    return None if v is None else v & m


def firing(recs, s: int, width: int, states, cmap, M, read_keys, G=None,
           known: dict | None = None, wires: dict | None = None):
    """[(record, destination value or None, condition text)] for every non-reset record that can
    fire in state s: source test matches, state-decided guards hold, not surely overwritten
    later in its block. The text drops guards that only restate the source state (or the
    inactive reset)."""
    out = []
    memo: dict = {}
    ctx = make_ctx(s, M, read_keys, G, memo, known, wires)
    for r in recs:
        if r.in_reset or not src_matches(r, s, states, cmap, width):
            continue
        ok, repl = guards_hold(r, s, M, read_keys, G, memo, known, wires)
        if not ok or overwritten(r, s, ctx, read_keys, width):
            continue
        rest = [x for x in (repl.get(c, c) for c in r.conds) if x]
        if len(rest) > 1:  # repeated factors (`a && !b && !b`) collapse, order kept
            rest = list(dict.fromkeys(f for c in rest for f in split_and(c)))
        text = " && ".join(l1fsm._paren(c) for c in rest) if rest else "1"
        out.append((r, rec_dst(r, s, width, states, cmap), text))
    return out


def applicable(recs, s: int, d: int, width: int, states, cmap, M, read_keys, G=None,
               known: dict | None = None, wires: dict | None = None):
    """[(record, condition text)] of the records in `firing` that produce s -> d."""
    return [(r, t) for r, v, t in firing(recs, s, width, states, cmap, M, read_keys, G, known,
                                         wires) if v == d]


def hold_guard(fires, s: int) -> str | None:
    """Guard of the hold self-loop of s derived from its exits: !(e1 || e2 ...), when every
    record that can fire in s has a known destination and a condition (None otherwise, or when
    an exit is unconditional)."""
    exits = []
    for _, v, t in fires:
        if v is None:
            return None
        if v != s:
            exits.append(t)
    if "1" in exits:
        return None
    if not exits:
        return "1"
    return neg_or(list(dict.fromkeys(exits)))


def split_and(t: str) -> list[str]:
    """Top-level `&&` factors of a condition text (outer parentheses of a factor removed)."""
    parts, depth, cur, i = [], 0, "", 0
    while i < len(t):
        ch = t[i]
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and t.startswith("&&", i):
            parts.append(cur.strip())
            cur, i = "", i + 2
            continue
        cur += ch
        i += 1
    parts.append(cur.strip())
    return [x[1:-1].strip() if l1fsm._wrapped(x) and "||" not in x else x for x in parts if x]


def neg(t: str) -> str:
    """!t with `!(!(x))` -> x and `!(x)` -> x for a wrapped negation."""
    if t.startswith("!") and l1fsm._wrapped(t[1:]):
        return t[2:-1].strip()
    return l1fsm._neg(t)


def neg_or(texts: list[str]) -> str:
    """!(t1 || t2 ...) with two textual simplifications: shared `&&` factors are pulled out,
    and a factor list whose remainders are x / !x (or empty) collapses to the shared part."""
    fs = [split_and(t) for t in texts]
    common = [x for x in fs[0] if all(x in f for f in fs[1:])]
    rests = [[x for x in f if x not in common] for f in fs]
    flat = {r[0] for r in rests if len(r) == 1}
    covers = any(not r for r in rests) or (
        all(len(r) == 1 for r in rests) and any(neg(x) in flat for x in flat))
    if common and covers:
        return " || ".join(l1fsm._paren(neg(x)) for x in common)
    if len(texts) == 1:
        return neg(texts[0])
    return "!(" + " || ".join(f"({t})" for t in texts) + ")"


# --------------------------------------------------------------- naming helpers
def bit_index_constants(design, G, read_keys: set[str]) -> dict[int, dict]:
    """K -> {name, file, line} for every `s[NAME]` select whose index is a named parameter."""
    found: dict[int, dict] = {}
    conflicts: set[int] = set()

    def cb(n):
        if isinstance(n, ast.ElementSelectExpression):
            v = l1fsm._strip(n.value)
            sel = l1fsm._strip(n.selector)
            if (
                isinstance(v, ast.ValueExpressionBase)
                and v.symbol.kind in (ast.SymbolKind.Variable, ast.SymbolKind.Net)
                and v.symbol.hierarchicalPath in read_keys
                and isinstance(sel, ast.ValueExpressionBase)
                and isinstance(sel.symbol, ast.ParameterSymbol)
            ):
                k = const_int(sel)
                if k is not None:
                    loc = src_line(design, n) or {"file": "", "line": 0}
                    prev = found.get(k)
                    if prev and prev["name"] != sel.symbol.name:
                        conflicts.add(k)
                    elif not prev:
                        found[k] = {"name": sel.symbol.name, **loc}
        return True

    for path in sorted({G.nodes[k].inst for k in read_keys}):
        inst = l1fsm._find_instance(design, path)
        if inst is None:
            continue
        for m in l1fsm._members(inst.body):
            node = None
            if isinstance(m, ast.ProceduralBlockSymbol):
                node = m.body
            elif isinstance(m, ast.ContinuousAssignSymbol):
                node = m.assignment
            if node is not None:
                try:
                    node.visit(cb)
                except Exception:
                    pass
    return {k: v for k, v in found.items() if k not in conflicts}


def bit_alias_wires(design, G, read_keys: set[str]) -> dict[int, dict]:
    """value 1 << K -> {name, file, line} for `assign NAME = s[K];` (a wire that only taps one
    bit of the register); bits tapped by two different wires are dropped."""
    found: dict[int, dict] = {}
    dup: set[int] = set()
    for path in sorted({G.nodes[k].inst for k in read_keys}):
        inst = l1fsm._find_instance(design, path)
        if inst is None:
            continue
        for m in l1fsm._members(inst.body):
            if not isinstance(m, ast.ContinuousAssignSymbol):
                continue
            a = m.assignment
            if not isinstance(a, ast.AssignmentExpression):
                continue
            lhs, rhs = l1fsm._strip(a.left), l1fsm._strip(a.right)
            if not (isinstance(lhs, ast.ValueExpressionBase)
                    and isinstance(rhs, ast.ElementSelectExpression)):
                continue
            v = l1fsm._strip(rhs.value)
            if not (isinstance(v, ast.ValueExpressionBase)
                    and v.symbol.hierarchicalPath in read_keys):
                continue
            k = const_int(rhs.selector)
            if k is None:
                continue
            val = 1 << k
            if val in found and found[val]["name"] != lhs.symbol.name:
                dup.add(val)
            found.setdefault(val, {"name": lhs.symbol.name,
                                   **(src_line(design, a) or {"file": "", "line": 0})})
    return {v: x for v, x in found.items() if v not in dup}


def macro_names(design, G, S: str, read_keys: set[str]) -> dict[int, dict]:
    """value -> {name, file, line} for literal state codes written as `MACRO in assignments to
    the register, comparisons with it, or case items on it (unique macro per value only)."""
    seen: dict[int, set[str]] = {}
    where: dict[int, dict] = {}
    width = G.nodes[S].width or 1
    sm = design.sm

    def note(e):
        e = l1fsm._strip(e)
        if isinstance(e, ast.ConditionalExpression):
            note(e.left)
            note(e.right)
            return
        if not isinstance(e, ast.IntegerLiteral):
            return
        loc = e.sourceRange.start
        try:
            if not sm.isMacroLoc(loc):
                return
            name = str(sm.getMacroName(loc))
        except Exception:
            return
        v = const_int(e)
        if v is None or not name:
            return
        v &= _mask(width)
        seen.setdefault(v, set()).add(name)
        where.setdefault(v, {"name": name, **(src_line(design, e) or {"file": "", "line": 0})})

    def key(e):
        e = l1fsm._strip(e)
        if isinstance(e, ast.ValueExpressionBase) and e.symbol.kind in (
            ast.SymbolKind.Variable, ast.SymbolKind.Net,
        ):
            return e.symbol.hierarchicalPath
        return None

    def cb(n):
        if isinstance(n, ast.AssignmentExpression) and set(_lroots(n.left)) & read_keys:
            note(n.right)
        elif isinstance(n, ast.BinaryExpression) and _op(n) in (
            "Equality", "CaseEquality", "Inequality", "CaseInequality",
        ):
            if key(n.left) in read_keys:
                note(n.right)
            elif key(n.right) in read_keys:
                note(n.left)
        elif isinstance(n, ast.CaseStatement) and key(n.expr) in read_keys:
            for it in n.items:
                for x in it.expressions:
                    note(x)
        return True

    for path in sorted({G.nodes[k].inst for k in read_keys}):
        inst = l1fsm._find_instance(design, path)
        if inst is None:
            continue
        for m in l1fsm._members(inst.body):
            node = m.body if isinstance(m, ast.ProceduralBlockSymbol) else (
                m.assignment if isinstance(m, ast.ContinuousAssignSymbol) else None)
            if node is not None:
                try:
                    node.visit(cb)
                except Exception:
                    pass
    return {v: where[v] for v, names in seen.items() if len(names) == 1}
