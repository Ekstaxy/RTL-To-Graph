"""Semantic (coding-style independent) FSM extraction by executing the elaborated RTL.

The syntactic extractor (fsm.py) reads `case (state)` / `state == X` patterns and therefore breaks
on equivalent rewrites (one-hot bit equations, if-chains with compound guards, next-state logic in
a submodule...). This module instead *evaluates* the design:

  * a small cycle-based interpreter over slang's AST (continuous assigns, combinational and
    edge-triggered procedural blocks, functions, for-loops, case/casez, part selects) that follows
    signals across instance ports, so hierarchy does not matter;
  * the reset value of a state register is found by asserting each candidate reset level;
  * from the reset value, a BFS over states: for every reached state value, many input/free-register
    samples (random + every literal constant of the design +/-1) give the next-state values.

Two equivalent designs therefore produce isomorphic state graphs regardless of how they are written.
Sampling is sound (every reported transition is produced by the RTL for some value assignment of the
sampled signals) but not complete for rare conditions; constants from the RTL are always tried.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from pyslang import ast

from .elab import Design
from .graph import DesignGraph, EdgeType


class Unsupported(Exception):
    pass


_LIT = re.compile(r"^(?:(\d+)\s*)?'(s?)([bodhBODH])([0-9a-fA-FxXzZ?_]+)$")


def _parse_const(text: str) -> tuple[int, int | None, int]:
    """Verilog constant text -> (value, width or None, care_mask). x/z/? bits are don't-care
    (value 0)."""
    t = text.strip().replace("_", "")
    m = _LIT.match(t)
    if m:
        width = int(m.group(1)) if m.group(1) else None
        base = {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(3).lower()]
        digits = m.group(4)
        bits_per = {2: 1, 8: 3, 16: 4}.get(base)
        if base == 10:
            if re.search(r"[xXzZ?]", digits):
                return 0, width, 0
            v = int(digits)
            return v, width, (1 << width) - 1 if width else -1
        val = care = 0
        for ch in digits:
            val <<= bits_per
            care <<= bits_per
            if ch in "xXzZ?":
                continue
            val |= int(ch, base)
            care |= (1 << bits_per) - 1
        return val, width, care
    if re.fullmatch(r"-?\d+", t):
        return int(t), None, -1
    if t in ("'0", "'1", "'x", "'z"):
        return (0 if t != "'1" else -1), None, (0 if t in ("'x", "'z") else -1)
    raise Unsupported(f"constant {text!r}")


def _cv_int(cv) -> tuple[int, int]:
    s = str(cv)
    v, _, care = _parse_const(s)
    return v, care


def _mask(w: int) -> int:
    return (1 << w) - 1 if w > 0 else -1


def _sx(v: int, w: int) -> int:
    v &= _mask(w)
    return v - (1 << w) if w > 0 and v >> (w - 1) & 1 else v


def _width(e) -> int:
    try:
        w = e.type.bitWidth
        return int(w) if w else 1
    except Exception:
        return 1


def _signed(e) -> bool:
    try:
        return bool(e.type.isSigned)
    except Exception:
        return False


def _members(scope):
    for m in scope:
        if isinstance(m, ast.GenerateBlockSymbol):
            if not m.isUninstantiated:
                yield from _members(m)
        elif isinstance(m, ast.GenerateBlockArraySymbol):
            for e in m.entries:
                if not e.isUninstantiated:
                    yield from _members(e)
        else:
            yield m


def _key(sym) -> str:
    return sym.hierarchicalPath


def _is_ff(pb) -> bool:
    if pb.procedureKind == ast.ProceduralBlockKind.AlwaysFF:
        return True
    b = pb.body
    if pb.procedureKind == ast.ProceduralBlockKind.Always and isinstance(b, ast.TimedStatement):
        t = b.timing
        evs = list(t.events) if isinstance(t, ast.EventListControl) else [t]
        return any(
            isinstance(x, ast.SignalEventControl)
            and x.edge in (ast.EdgeKind.PosEdge, ast.EdgeKind.NegEdge)
            for x in evs
        )
    return False


def _lroots(e) -> list[str]:
    """Root variables written by an lvalue expression."""
    while isinstance(e, ast.ConversionExpression):
        e = e.operand
    if isinstance(e, ast.ValueExpressionBase):
        return [_key(e.symbol)]
    if isinstance(
        e, (ast.ElementSelectExpression, ast.RangeSelectExpression, ast.MemberAccessExpression)
    ):
        return _lroots(e.value)
    if isinstance(e, ast.ConcatenationExpression):
        return [k for x in e.operands for k in _lroots(x)]
    return []


def _assigned(st, out: set):
    if st is None:
        return
    if isinstance(st, ast.BlockStatement):
        return _assigned(st.body, out)
    if isinstance(st, ast.TimedStatement):
        return _assigned(st.stmt, out)
    if isinstance(st, ast.StatementList):
        for x in st.list:
            _assigned(x, out)
        return
    if isinstance(st, ast.ConditionalStatement):
        _assigned(st.ifTrue, out)
        _assigned(st.ifFalse, out)
        return
    if isinstance(st, ast.CaseStatement):
        for it in st.items:
            _assigned(it.stmt, out)
        _assigned(st.defaultCase, out)
        return
    if isinstance(
        st,
        (
            ast.ForLoopStatement,
            ast.WhileLoopStatement,
            ast.RepeatLoopStatement,
            ast.ForeachLoopStatement,
        ),
    ):
        return _assigned(st.body, out)
    if isinstance(st, ast.ExpressionStatement) and isinstance(st.expr, ast.AssignmentExpression):
        out.update(_lroots(st.expr.left))


class Machine:
    """Flattened, demand-driven evaluator for one elaborated design."""

    def __init__(self, design: Design, seed: int = 0):
        self.design = design
        self.cont: dict[
            str, list
        ] = {}  # key -> continuous assignments / net initializers writing it
        self.comb: dict[str, list] = {}  # key -> combinational procedural blocks writing it
        self.ff: dict[str, list] = {}  # key -> edge-triggered blocks writing it
        self.port_in: dict[str, object] = {}  # child input port key -> parent expression
        self.port_out: dict[
            str, list
        ] = {}  # parent root key -> [(child port key, parent lvalue expr)]
        self.consts: set[int] = {0, 1}
        self.rng = random.Random(seed)
        for top in design.tops:
            self._index(top)

    # ----------------------------------------------------------------- index
    def _index(self, inst):
        for m in _members(inst.body):
            if isinstance(m, ast.ContinuousAssignSymbol) and isinstance(
                m.assignment, ast.AssignmentExpression
            ):
                for k in _lroots(m.assignment.left):
                    self.cont.setdefault(k, []).append(("assign", m.assignment))
                self._collect_consts(m.assignment)
            elif isinstance(m, ast.NetSymbol) and m.initializer is not None:
                self.cont.setdefault(_key(m), []).append(("init", m.initializer))
            elif isinstance(m, ast.ProceduralBlockSymbol):
                if m.procedureKind in (
                    ast.ProceduralBlockKind.Initial,
                    ast.ProceduralBlockKind.Final,
                ):
                    continue
                tg: set[str] = set()
                _assigned(m.body, tg)
                bucket = self.ff if _is_ff(m) else self.comb
                for k in tg:
                    if m not in bucket.setdefault(k, []):
                        bucket[k].append(m)
                self._collect_consts(m.body)
            elif isinstance(m, ast.InstanceSymbol) and m.isModule:
                for pc in m.portConnections:
                    port, e = pc.port, pc.expression
                    if (
                        not isinstance(port, ast.PortSymbol)
                        or port.internalSymbol is None
                        or e is None
                    ):
                        continue
                    ck = _key(port.internalSymbol)
                    if port.direction == ast.ArgumentDirection.In:
                        self.port_in[ck] = e.right if isinstance(e, ast.AssignmentExpression) else e
                    elif port.direction == ast.ArgumentDirection.Out:
                        lhs = e.left if isinstance(e, ast.AssignmentExpression) else e
                        for k in _lroots(lhs):
                            self.port_out.setdefault(k, []).append((ck, lhs))
                self._index(m)
            elif isinstance(m, ast.InstanceArraySymbol):
                for el in m.elements:
                    if isinstance(el, ast.InstanceSymbol):
                        self._index(el)

    def _collect_consts(self, node):
        def cb(n):
            if isinstance(n, (ast.IntegerLiteral,)):
                try:
                    v, _, _ = _parse_const(
                        str(n.constant) if n.constant is not None else n.syntax.__str__()
                    )
                    if 0 <= v < (1 << 32):
                        self.consts.add(v)
                except Exception:
                    pass
            if isinstance(n, ast.ValueExpressionBase) and isinstance(
                n.symbol, (ast.ParameterSymbol, ast.EnumValueSymbol)
            ):
                try:
                    v, _ = _cv_int(n.symbol.value)
                    if 0 <= v < (1 << 32):
                        self.consts.add(v)
                except Exception:
                    pass
            return True

        try:
            node.visit(cb)
        except Exception:
            pass

    # ---------------------------------------------------------------- sample
    def sample(self, width: int) -> int:
        m = _mask(min(width, 64))
        r = self.rng.random()
        if r < 0.45:
            c = self.rng.choice(sorted(self.consts))
            c += self.rng.choice((-1, 0, 0, 0, 1))
            return c & m
        if r < 0.55:
            return m
        return self.rng.getrandbits(min(width, 64)) & m

    # -------------------------------------------------------------- one cycle
    def new_cycle(self, env: dict):
        self.env = env  # current values of registers / inputs (sampled lazily)
        self.cache: dict = {}
        self.busy: set = set()
        self.blocks_done: set = set()

    def width_of(self, key: str) -> int:
        n = self.design and self._graph_width.get(key) if hasattr(self, "_graph_width") else None
        return n or 32

    def value(self, key: str, width_hint: int = 32):
        """Value of a signal in the current cycle (scalar int or dict for unpacked arrays)."""
        if key in self.cache:
            return self.cache[key]
        if key in self.env:
            return self.env[key]
        if key in self.busy:
            raise Unsupported(f"combinational loop at {key}")
        self.busy.add(key)
        try:
            if key in self.comb:
                for pb in self.comb[key]:
                    self._run_comb(pb)
                if key in self.cache:
                    return self.cache[key]
            if key in self.cont:
                cur = self.cache.get(key, 0)
                self.cache[key] = cur
                for kind, a in self.cont[key]:
                    if kind == "init":
                        self.cache[key] = self.ev(a)
                    else:
                        self._write(a.left, self.ev(a.right), self.cache, self.cache)
                return self.cache[key]
            if key in self.port_in:
                v = self.ev(self.port_in[key])
                self.cache[key] = v
                return v
            if key in self.port_out:
                cur = 0
                tmp = {key: cur}
                for ck, lhs in self.port_out[key]:
                    self._write(lhs, self.value(ck), tmp, tmp)
                self.cache[key] = tmp[key]
                return tmp[key]
            # free variable (top input, register, undriven): sample once per cycle
            v = self.sample(width_hint)
            self.env[key] = v
            return v
        finally:
            self.busy.discard(key)

    # --------------------------------------------------------------- blocks
    def _run_comb(self, pb):
        if id(pb) in self.blocks_done:
            return
        self.blocks_done.add(id(pb))
        store: dict = {}
        self._exec(pb.body, store, None)
        self.cache.update(store)

    def next_values(self, key: str) -> dict:
        """Run the edge-triggered blocks writing `key`; return their nonblocking updates."""
        nb: dict = {}
        for pb in self.ff.get(key, []):
            store: dict = {}
            self._exec(pb.body, store, nb)
        return nb

    # ------------------------------------------------------------ statements
    def _read(self, key, store, width_hint=32):
        if store is not None and key in store:
            return store[key]
        return self.value(key, width_hint)

    def _exec(self, st, store, nb, depth=0):
        if st is None:
            return
        if isinstance(st, ast.BlockStatement):
            return self._exec(st.body, store, nb)
        if isinstance(st, ast.TimedStatement):
            return self._exec(st.stmt, store, nb)
        if isinstance(st, ast.StatementList):
            for x in st.list:
                self._exec(x, store, nb)
            return
        if isinstance(st, ast.ConditionalStatement):
            c = self.ev(st.conditions[0].expr, store)
            return self._exec(st.ifTrue if c else st.ifFalse, store, nb)
        if isinstance(st, ast.CaseStatement):
            sel = self.ev(st.expr, store)
            w = _width(st.expr)
            wild = str(st.condition).split(".")[-1] in ("WildcardXOrZ", "WildcardJustZ")
            for it in st.items:
                for x in it.expressions:
                    if self._case_match(sel, w, x, store, wild):
                        return self._exec(it.stmt, store, nb)
            return self._exec(st.defaultCase, store, nb)
        if isinstance(st, ast.ForLoopStatement):
            for x in st.initializers:
                if isinstance(x, ast.AssignmentExpression):
                    self._write(x.left, self.ev(x.right, store), store, store)
            for v in st.loopVars:
                if v.initializer is not None:
                    store[_key(v)] = self.ev(v.initializer, store)
            for _ in range(4096):
                if st.stopExpr is not None and not self.ev(st.stopExpr, store):
                    break
                self._exec(st.body, store, nb)
                for s in st.steps:
                    self._expr_effect(s, store)
            return
        if isinstance(st, ast.ExpressionStatement):
            return self._expr_effect(st.expr, store, nb)
        if isinstance(st, ast.VariableDeclStatement):
            if st.symbol.initializer is not None:
                store[_key(st.symbol)] = self.ev(st.symbol.initializer, store)
            return
        if isinstance(st, ast.EmptyStatement) if hasattr(ast, "EmptyStatement") else False:
            return
        kind = str(st.kind).split(".")[-1]
        if kind in ("Empty", "ImmediateAssertion", "ConcurrentAssertion", "Return"):
            return
        raise Unsupported(f"statement {kind}")

    def _expr_effect(self, e, store, nb=None):
        if isinstance(e, ast.AssignmentExpression):
            rhs = self.ev(e.right, store)
            if e.isCompound:
                raise Unsupported("compound assignment")
            if e.isNonBlocking and nb is not None:
                self._write(e.left, rhs, nb, store, base_from=store)
            else:
                self._write(e.left, rhs, store, store)
            return
        if isinstance(e, ast.UnaryExpression):
            op = str(e.op).split(".")[-1]
            if op in ("Preincrement", "Postincrement", "Predecrement", "Postdecrement"):
                v = self.ev(e.operand, store) + (1 if "incr" in op else -1)
                self._write(e.operand, v, store, store)
                return
        if isinstance(e, ast.CallExpression):
            return  # system task ($display, ...): no state effect
        raise Unsupported(f"expression statement {str(e.kind)}")

    def _case_match(self, sel, w, x, store, wild):
        if wild and x.constant is not None:
            v, care = _cv_int(x.constant)
            return (sel ^ v) & care & _mask(w) == 0
        return (sel & _mask(w)) == (self.ev(x, store) & _mask(w))

    # --------------------------------------------------------- write lvalue
    def _write(self, lhs, value, target: dict, store: dict, base_from: dict | None = None):
        while isinstance(lhs, ast.ConversionExpression):
            lhs = lhs.operand
        if isinstance(lhs, ast.ValueExpressionBase):
            target[_key(lhs.symbol)] = (
                value & _mask(_width(lhs)) if isinstance(value, int) else value
            )
            return
        if isinstance(lhs, ast.ConcatenationExpression):
            shift = sum(_width(x) for x in lhs.operands)
            for x in lhs.operands:
                w = _width(x)
                shift -= w
                self._write(x, (value >> shift) & _mask(w), target, store, base_from)
            return
        if isinstance(lhs, (ast.ElementSelectExpression, ast.RangeSelectExpression)):
            roots = _lroots(lhs)
            if len(roots) != 1:
                raise Unsupported("complex lvalue")
            root = roots[0]
            base = target.get(root)
            if base is None:
                src = base_from if base_from is not None else store
                base = (
                    src.get(root)
                    if src is not None and root in src
                    else self._cur_for_write(root, lhs)
                )
            new = self._insert(lhs, base, value, store)
            target[root] = new
            return
        raise Unsupported(f"lvalue {str(lhs.kind)}")

    def _cur_for_write(self, root, lhs):
        try:
            return self.value(root)
        except Unsupported:
            return 0

    def _insert(self, lhs, base, value, store):
        """Return `base` with the selected part replaced by `value` (recursive for nested
        selects)."""
        inner = lhs.value
        while isinstance(inner, ast.ConversionExpression):
            inner = inner.operand
        vt = inner.type
        if isinstance(lhs, ast.ElementSelectExpression) and vt.isUnpackedArray:
            idx = self.ev(lhs.selector, store)
            arr = dict(base) if isinstance(base, dict) else {}
            arr[idx] = value & _mask(_width(lhs))
            return (
                self._replace_inner(inner, arr, store)
                if not isinstance(inner, ast.ValueExpressionBase)
                else arr
            )
        lo, w = self._sel_bits(lhs, store)
        if isinstance(base, dict):
            raise Unsupported("packed select of array")
        b = int(base) & ~(_mask(w) << lo) | ((value & _mask(w)) << lo)
        if isinstance(inner, ast.ValueExpressionBase):
            return b
        raise Unsupported("nested packed lvalue")

    def _replace_inner(self, inner, arr, store):
        raise Unsupported("nested array lvalue")

    def _sel_bits(self, e, store) -> tuple[int, int]:
        """(lsb offset, width) of a packed element/range select."""
        vt = e.value.type
        try:
            rng = vt.fixedRange
            lower, desc, left = rng.lower, rng.isDescending, rng.left
        except Exception:
            lower, desc, left = 0, True, 0
        ew = _width(e)
        if isinstance(e, ast.ElementSelectExpression):
            idx = self.ev(e.selector, store)
            off = (idx - lower) if desc else (left - idx) if False else (idx - lower)
            return off * ew, ew
        kind = str(e.selectionKind).split(".")[-1]
        if kind == "Simple":
            a, b = self.ev(e.left, store), self.ev(e.right, store)
            lo = min(a, b) - lower
            return lo * (ew // max(1, abs(a - b) + 1)), ew
        base = self.ev(e.left, store)
        width = self.ev(e.right, store)
        elem = ew // max(1, width)
        if kind == "IndexedUp":
            return (base - lower) * elem, ew
        return (base - width + 1 - lower) * elem, ew

    # ---------------------------------------------------------- expressions
    def ev(self, e, store=None):
        w = _width(e)
        v = self._ev(e, store)
        if isinstance(v, dict):
            return v
        return v & _mask(w) if w > 0 else v

    def _ev(self, e, store):
        if isinstance(e, ast.ValueExpressionBase):
            sym = e.symbol
            if isinstance(sym, (ast.ParameterSymbol, ast.EnumValueSymbol)):
                return _cv_int(sym.value)[0]
            if sym.kind in (
                ast.SymbolKind.Variable,
                ast.SymbolKind.Net,
                ast.SymbolKind.FormalArgument,
            ):
                return self._read(_key(sym), store, _width(e))
            raise Unsupported(f"value of {sym.kind}")
        try:
            c = e.constant
        except Exception:
            c = None
        if c is not None and not isinstance(e, ast.AssignmentExpression):
            try:
                return _cv_int(c)[0]
            except Unsupported:
                pass
        if isinstance(e, (ast.IntegerLiteral, ast.UnbasedUnsizedIntegerLiteral)):
            v, _, _ = _parse_const(str(e.syntax))
            if isinstance(e, ast.UnbasedUnsizedIntegerLiteral) and v == -1:
                return _mask(_width(e))
            return v
        if isinstance(e, ast.ConversionExpression):
            v = self.ev(e.operand, store)
            if isinstance(v, dict):
                return v
            if _signed(e.operand):
                return _sx(v, _width(e.operand))
            return v
        if isinstance(e, ast.UnaryExpression):
            op = str(e.op).split(".")[-1]
            v = self.ev(e.operand, store)
            w = _width(e.operand)
            if op == "Plus":
                return v
            if op == "Minus":
                return -v
            if op == "BitwiseNot":
                return ~v
            if op == "LogicalNot":
                return int(v == 0)
            if op == "BitwiseAnd":
                return int((v & _mask(w)) == _mask(w))
            if op == "BitwiseOr":
                return int(v != 0)
            if op == "BitwiseXor":
                return bin(v & _mask(w)).count("1") & 1
            if op == "BitwiseNand":
                return int((v & _mask(w)) != _mask(w))
            if op == "BitwiseNor":
                return int(v == 0)
            if op == "BitwiseXnor":
                return 1 - (bin(v & _mask(w)).count("1") & 1)
            raise Unsupported(f"unary {op}")
        if isinstance(e, ast.BinaryExpression):
            op = str(e.op).split(".")[-1]
            if op == "LogicalAnd":
                return int(bool(self.ev(e.left, store)) and bool(self.ev(e.right, store)))
            if op == "LogicalOr":
                return int(bool(self.ev(e.left, store)) or bool(self.ev(e.right, store)))
            a, b = self.ev(e.left, store), self.ev(e.right, store)
            wl, wr = _width(e.left), _width(e.right)
            sg = _signed(e.left) and _signed(e.right)
            if op in ("Equality", "CaseEquality", "WildcardEquality"):
                return int(a == b)
            if op in ("Inequality", "CaseInequality", "WildcardInequality"):
                return int(a != b)
            if op in ("LessThan", "LessThanEqual", "GreaterThan", "GreaterThanEqual"):
                if sg:
                    a, b = _sx(a, wl), _sx(b, wr)
                return int(
                    {
                        "LessThan": a < b,
                        "LessThanEqual": a <= b,
                        "GreaterThan": a > b,
                        "GreaterThanEqual": a >= b,
                    }[op]
                )
            if op == "Add":
                return a + b
            if op == "Subtract":
                return a - b
            if op == "Multiply":
                return a * b
            if op in ("Divide", "Mod"):
                if b == 0:
                    return 0
                return a // b if op == "Divide" else a % b
            if op == "BinaryAnd":
                return a & b
            if op == "BinaryOr":
                return a | b
            if op == "BinaryXor":
                return a ^ b
            if op == "BinaryXnor":
                return ~(a ^ b)
            if op in ("LogicalShiftLeft", "ArithmeticShiftLeft"):
                return a << min(b, 4096)
            if op == "LogicalShiftRight":
                return a >> min(b, 4096)
            if op == "ArithmeticShiftRight":
                return (_sx(a, wl) if _signed(e.left) else a) >> min(b, 4096)
            if op == "Power":
                return a ** min(b, 64)
            if op == "LogicalImplication":
                return int((not a) or bool(b))
            if op == "LogicalEquivalence":
                return int(bool(a) == bool(b))
            raise Unsupported(f"binary {op}")
        if isinstance(e, ast.ConditionalExpression):
            c = self.ev(e.conditions[0].expr, store)
            return self.ev(e.left if c else e.right, store)
        if isinstance(e, ast.ConcatenationExpression):
            v = 0
            for x in e.operands:
                w = _width(x)
                if w == 0:
                    continue
                v = (v << w) | (self.ev(x, store) & _mask(w))
            return v
        if isinstance(e, ast.ReplicationExpression):
            n = self.ev(e.count, store)
            inner = self.ev(e.concat, store)
            w = _width(e.concat)
            v = 0
            for _ in range(n):
                v = (v << w) | (inner & _mask(w))
            return v
        if isinstance(e, ast.ElementSelectExpression):
            base = self.ev(e.value, store)
            if isinstance(base, dict) or e.value.type.isUnpackedArray:
                idx = self.ev(e.selector, store)
                arr = base if isinstance(base, dict) else {}
                if idx not in arr:
                    arr[idx] = self.sample(_width(e))  # unknown memory word: free variable
                    if isinstance(e.value, ast.ValueExpressionBase):
                        self.env.setdefault(_key(e.value.symbol), arr)
                return arr[idx]
            lo, w = self._sel_bits(e, store)
            return (base >> lo) & _mask(w) if lo >= 0 else 0
        if isinstance(e, ast.RangeSelectExpression):
            base = self.ev(e.value, store)
            if isinstance(base, dict):
                raise Unsupported("range select of array")
            lo, w = self._sel_bits(e, store)
            return (base >> lo) & _mask(w) if lo >= 0 else 0
        if isinstance(e, ast.InsideExpression):
            v = self.ev(e.left, store)
            return int(any(v == self.ev(x, store) for x in e.rangeList))
        if isinstance(e, ast.CallExpression):
            if e.isSystemCall:
                name = e.subroutineName
                if name in ("$signed", "$unsigned"):
                    return self.ev(e.arguments[0], store)
                raise Unsupported(f"system call {name}")
            return self._call(e, store)
        if isinstance(e, ast.AssignmentExpression):
            v = self.ev(e.right, store)
            self._write(e.left, v, store, store)
            return v
        raise Unsupported(f"expression {str(e.kind)}")

    def _call(self, e, store):
        sub = e.subroutine
        if not isinstance(sub, ast.SubroutineSymbol):
            raise Unsupported("call")
        local: dict = dict(store or {})
        for formal, actual in zip(sub.arguments, e.arguments, strict=False):
            local[_key(formal)] = self.ev(actual, store)
        rv = sub.returnValVar
        self._exec(sub.body, local, None)
        if rv is not None and _key(rv) in local:
            return local[_key(rv)]
        return 0


@dataclass
class SemanticFSM:
    state: str  # node key
    reset_signal: str | None
    reset_level: int | None
    reset_value: int | None
    states: list[int] = field(default_factory=list)
    edges: set = field(default_factory=set)  # (src value, dst value)
    samples: int = 0
    error: str | None = None
    complete: bool = True

    def summary(self) -> dict:
        return {
            "state": self.state,
            "reset": self.reset_value,
            "n_states": len(self.states),
            "n_edges": len({(a, b) for a, b in self.edges if a != b}),
            "error": self.error,
        }


def analyze(
    design: Design,
    G: DesignGraph,
    key: str,
    *,
    samples_per_state: int = 300,
    max_states: int = 48,
    seed: int = 0,
    machine: Machine | None = None,
) -> SemanticFSM:
    M = machine or Machine(design, seed)
    width = G.nodes[key].width or 1
    resets = sorted({p for p, _ in G.preds(key, {EdgeType.RESET})})
    res = SemanticFSM(
        state=key, reset_signal=resets[0] if resets else None, reset_level=None, reset_value=None
    )
    if key not in M.ff:
        res.error = "no edge-triggered driver"
        return res

    def step(env):
        M.new_cycle(env)
        nb = M.next_values(key)
        v = nb.get(key, env.get(key))
        if isinstance(v, dict):
            raise Unsupported("array state")
        return v & _mask(width)

    # semantic reset candidates: besides structurally detected resets, any 1-bit input port in the
    # register's fan-in cone (a reset written as `rst ? IDLE : nxt` is not structurally a reset)
    cone, frontier = set(), [key]
    for _ in range(6):
        nxt = []
        for k in frontier:
            for p, et in G.preds(k):
                if p not in cone and et != EdgeType.CLOCK:
                    cone.add(p)
                    if not G.nodes[p].is_state:
                        nxt.append(p)
        frontier = nxt
    top_inputs = [
        p
        for p in cone
        if G.nodes[p].port_dir == "in"
        and G.nodes[p].width == 1
        and G.nodes[p].inst in G.tops
        and p not in resets
    ]
    resets = resets + sorted(top_inputs)

    try:
        # reset value: the level of a reset signal that forces a constant next value from ANY state
        rv = None
        for r in resets:
            for lvl in (0, 1):
                vals = set()
                # state encodings are constants of the design: try each of them, plus random values
                probes = [c & _mask(width) for c in sorted(M.consts)][:64] + [
                    M.sample(width) for _ in range(64)
                ]
                for sv in probes:
                    vals.add(step({r: lvl, key: sv}))
                    if len(vals) > 1:
                        break
                if len(vals) == 1:
                    rv, res.reset_signal, res.reset_level = vals.pop(), r, lvl
                    break
            if rv is not None:
                break
        if rv is None:
            rv = 0  # power-up / no reset: start from zero like the equivalence checker
        res.reset_value = rv
        inactive = (
            {res.reset_signal: 1 - res.reset_level}
            if res.reset_signal is not None and res.reset_level is not None
            else {}
        )
        seen, frontier = {rv}, [rv]
        while frontier:
            s = frontier.pop(0)
            for _ in range(samples_per_state):
                env = {key: s, **inactive}
                n = step(env)
                res.samples += 1
                res.edges.add((s, n))
                if n not in seen:
                    seen.add(n)
                    frontier.append(n)
                    if len(seen) > max_states:
                        res.complete = False
                        res.error = f"more than {max_states} reachable values (not an FSM)"
                        res.states = sorted(seen)
                        return res
        res.states = sorted(seen)
    except Unsupported as ex:
        res.error = f"unsupported: {ex}"
    except RecursionError:
        res.error = "unsupported: recursion"
    return res


def detect(
    design: Design,
    G: DesignGraph,
    syntactic_keys: set[str] | None = None,
    *,
    seed: int = 0,
    samples_per_state: int = 300,
    time_budget: float | None = 60.0,
) -> list[SemanticFSM]:
    """Semantic FSM detection: every syntactic candidate, plus any small self-dependent register
    whose reachable value set from reset is a sparse code (3..48 values and fewer than
    2**width). Sparse codes catch one-hot / scrambled encodings written as bit equations, which
    syntax cannot see."""
    M = Machine(design, seed)
    syntactic_keys = set(syntactic_keys or ())
    out = []
    import time as _time

    t0 = _time.time()
    # syntactic candidates first, then the rest; stop exploring new ones when the budget is spent
    order = sorted(syntactic_keys) + sorted(set(candidate_registers(G)) - syntactic_keys)
    for k in order:
        if time_budget is not None and _time.time() - t0 > time_budget and k not in syntactic_keys:
            break
        r = analyze(design, G, k, machine=M, seed=seed, samples_per_state=samples_per_state)
        if r.error:
            if k in syntactic_keys:
                out.append(r)
            continue
        if k in syntactic_keys:
            out.append(r)
            continue
        n, w = len(r.states), G.nodes[k].width
        shaped = 3 <= n and (w >= 6 or n < (1 << w) or _decoded_as_value(G, k))
        # a controller branches on inputs and is not loaded from multi-bit data
        # (indices, CSRs, grants)
        branching = any(len({b for a, b in r.edges if a == s}) >= 2 for s in r.states)
        avg_out = len({(a, b) for a, b in r.edges}) / max(1, n)
        if shaped and branching and avg_out <= 3.5 and not _loads_data(G, k):
            out.append(r)
    return out


def _aliases(G: DesignGraph, k: str) -> set[str]:
    out, stack = {k}, [k]
    while stack:
        x = stack.pop()
        for nb, _et in G.succs(x, {EdgeType.PORT}) + G.preds(x, {EdgeType.PORT}):
            if nb not in out:
                out.add(nb)
                stack.append(nb)
    return out


def _loads_data(G: DesignGraph, k: str) -> bool:
    """True if the register's next value is fed (through combinational DATA paths) by a multi-bit
    signal other than itself: it is loaded with data, so it is a data register, not a controller."""
    own = _aliases(G, k)
    seen, frontier = set(own), [k]
    for _ in range(8):
        nxt = []
        for x in frontier:
            for p, et in G.preds(x, {EdgeType.DATA, EdgeType.PORT}):
                if p in seen or (et == EdgeType.DATA and G.is_partial(p, x)):
                    continue  # bit/part-select reads (in[3]) are control taps, not a data load
                seen.add(p)
                pn = G.nodes[p]
                if p in own:
                    continue
                if pn.width >= max(2, G.nodes[k].width - 1) and (
                    pn.is_state or pn.port_dir == "in"
                ):
                    return True  # a (nearly) as-wide register / input copied into the candidate
                if not pn.is_state:
                    nxt.append(p)
        frontier = nxt
    return False


def _decoded_as_value(G: DesignGraph, k: str) -> bool:
    """`case (x)` / `x == CONST` on the register or on any port alias of it (decoding may sit in a
    submodule, behind one or more instance ports)."""
    seen, stack = {k}, [k]
    while stack:
        x = stack.pop()
        if G.nodes[x].case_selector:
            return True
        for nb, et in G.succs(x, {EdgeType.PORT}) + G.succs(x, {EdgeType.DATA}):
            nn = G.nodes[nb]
            # follow pure aliases: ports and single-source wires
            if nb not in seen and (
                et == EdgeType.PORT
                or (not nn.is_state and nn.width == G.nodes[k].width and len(G.preds(nb)) == 1)
            ):
                seen.add(nb)
                stack.append(nb)
    return False


def state_graph(r: SemanticFSM):
    import networkx as nx

    g = nx.DiGraph()
    for s in r.states:
        g.add_node(s, reset=(s == r.reset_value))
    for a, b in r.edges:
        if a != b:
            g.add_edge(a, b)
    return g


def candidate_registers(G: DesignGraph, max_width: int = 16) -> list[str]:
    """Registers worth a semantic FSM check: small, self-dependent, not counters."""
    out = []
    for k, n in G.nodes.items():
        if not n.is_state or n.depth is not None or not (1 <= n.width <= max_width):
            continue
        if k in n.arith_srcs:
            continue
        # self-dependency through combinational logic, crossing instance ports (next-state logic may
        # live in a submodule): backward search over non-register nodes, up to 8 hops
        seen, frontier, found = set(), [k], False
        for _ in range(8):
            nxt = []
            for x in frontier:
                for p, et in G.preds(x):
                    if et in (EdgeType.CLOCK, EdgeType.RESET):
                        continue
                    if p == k:
                        found = True
                        break
                    if p not in seen and not G.nodes[p].is_state:
                        seen.add(p)
                        nxt.append(p)
                if found:
                    break
            if found or not nxt:
                break
            frontier = nxt
        if found:
            out.append(k)
    return out
