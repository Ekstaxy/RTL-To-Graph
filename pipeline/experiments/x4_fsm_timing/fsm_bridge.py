"""x4 FSM bridge (L2 stand-in, plan §2 Stage 2): fsm_ext.json -> FsmGraph v0.1, one per FSM.

    uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/fsm_bridge.py \
        runs/x4_fsm_timing/designs/<design>/fsm_ext.json [--design NAME] [--out DIR]

Input elements follow FORMATS.md (L1 `FSM.to_json()` + "extra"); a missing "extra" is handled
(values parsed from `states[].value` when L1 gave them, no source lines). Rules:
  * state ids `s.<name>`, transition ids `t.<n>` (0-based, order of first appearance);
  * `src="*"` is expanded to concrete sources (semantic_transitions when present, else all states),
    sources whose guard is false once `state == X` atoms (and single-assignment wires of the
    module that are pure functions of the state register, e.g. `wire on_e = (pos == `E)`, read
    from extra.file) are evaluated are pruned; the reset edge `* -> reset_state` guarded only by
    a reset signal becomes the entry arrow (reset_state null -> inferred from that edge);
  * extra.simplifications (e8) are copied first, then the bridge's own rows;
  * semantic edges whose endpoint is no state (values unknown) are dropped with a row;
  * duplicate (src, dst) edges are merged with " || ";
  * every expansion / prune / merge / drop is a `simplifications[]` row with its source lines;
  * G3: semantic_check in {consistent, consistent-subset, semantic-only} is ok, anything else
    (mismatch, unsupported, missing) is `status="rejected"`; G2 issues also reject.
Writes nothing unless run as a script (then `<out>/<module>.<state>.json`).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _sibling(name: str):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


x4_tools = _sibling("x4_tools")
fsm_spec = x4_tools.x4("fsm_spec")
fsm_check = x4_tools.x4("fsm_check")

OK_SEMANTIC = {"consistent", "consistent-subset", "semantic-only"}
DATAPATH = "<datapath condition>"
_RESET_NAME = re.compile(r"^(a|s)?(rst|reset|rst_n|rstn|resetn|reset_n|nreset|nrst|arst_b|rst_b)$",
                         re.I)

# ------------------------------------------------------------------ Verilog literal values


def parse_literal(text: str) -> int | None:
    """Value of a Verilog integer literal (`5`, `3'b101`, `'h1f`, `4'd2`); None if it has x/z
    digits or is not a literal."""
    t = text.strip().replace("_", "")
    if re.fullmatch(r"\d+", t):
        return int(t)
    m = re.fullmatch(r"(\d*)'[sS]?([bBoOdDhH])([0-9a-fA-F]+)", t)
    if not m:
        return None
    base = {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(2).lower()]
    try:
        v = int(m.group(3), base)
    except ValueError:
        return None
    if m.group(1):
        v &= (1 << int(m.group(1))) - 1
    return v


# ------------------------------------------------------------------ guard partial evaluation
_TOK = re.compile(r"\s*(\|\||&&|\(|\)|!(?!=))")


def _tokens(text: str) -> list[str]:
    out, pos = [], 0
    while pos < len(text):
        m = _TOK.match(text, pos)
        if m:
            out.append(m.group(1))
            pos = m.end()
            continue
        nxt = len(text)
        for op in ("||", "&&", "(", ")"):
            k = text.find(op, pos)
            if k != -1:
                nxt = min(nxt, k)
        k = pos
        while True:  # a '!' not followed by '=' also ends an atom
            k = text.find("!", k)
            if k == -1 or k >= nxt:
                break
            if text[k + 1: k + 2] != "=":
                nxt = k
                break
            k += 1
        atom = text[pos:nxt].strip()
        if atom:
            out.append(atom)
        pos = nxt
    return out


class _Parser:
    """or := and ('||' and)* ; and := un ('&&' un)* ; un := '!' un | '(' or ')' | ATOM"""

    def __init__(self, toks: list[str], atom):
        self.t, self.i, self.atom, self.hit = toks, 0, atom, False

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        self.i += 1
        return self.t[self.i - 1]

    def p_or(self):
        parts = [self.p_and()]
        while self.peek() == "||":
            self.take()
            parts.append(self.p_and())
        if any(p is True for p in parts):
            return True
        rest = list(dict.fromkeys(p for p in parts if p is not False))
        if any(_neg(p) in rest for p in rest):
            return True  # x || !x
        return False if not rest else " || ".join(rest)

    def p_and(self):
        parts = [self.p_un()]
        while self.peek() == "&&":
            self.take()
            parts.append(self.p_un())
        if any(p is False for p in parts):
            return False
        rest = list(dict.fromkeys(_par(p) for p in parts if p is not True))
        if any(_neg(p) in rest for p in rest):
            return False  # x && !x
        return True if not rest else " && ".join(rest)

    def p_un(self):
        tok = self.peek()
        if tok == "!":
            self.take()
            v = self.p_un()
            return (not v) if isinstance(v, bool) else f"!{_par(v, strict=True)}"
        if tok == "(":
            self.take()
            v = self.p_or()
            if self.take() != ")":
                raise ValueError("unbalanced")
            return v
        if tok in (None, ")", "&&", "||"):
            raise ValueError("unexpected token")
        tok = self.take()
        v = self.atom(tok)
        if isinstance(v, bool):
            self.hit = True
            return v
        return tok


def _neg(s: str) -> str:
    """Text of the negation of `s` in the form the parser builds it."""
    if s.startswith("!(") and s.endswith(")") and _balanced(s[2:-1]):
        return s[2:-1]
    if s.startswith("!") and re.fullmatch(r"[\w\[\]:.']+", s[1:]):
        return s[1:]
    return f"!{_par(s, strict=True)}"


def _balanced(s: str) -> bool:
    depth = 0
    for c in s:
        depth += (c == "(") - (c == ")")
        if depth < 0:
            return False
    return depth == 0


def _par(s: str, strict: bool = False) -> str:
    if isinstance(s, bool):
        return s
    simple = re.fullmatch(r"[\w\[\]:.']+", s) is not None
    if strict and not simple:
        return f"({s})"
    return f"({s})" if "||" in s else s


def specialise(guard: str, reg: str, src: str, values: dict[str, int | None],
               aliases: dict[str, dict[str, bool]] | None = None):
    """Partially evaluate `guard` for current state `src`: atoms `reg == X`, `reg != X`,
    `reg[K]` and wire aliases of such tests (`aliases[name][state]`, see `state_aliases`)
    become constants. Returns (result, touched): result is True / False / residual text
    (the original text when nothing was evaluated); None when the guard does not parse."""
    names = set(values)
    sv = values.get(src)
    aliases = aliases or {}

    def const(x: str):
        x = x.strip()
        if x in names:
            return ("name", x)
        v = parse_literal(x)
        return ("val", v) if v is not None else None

    def atom(a: str):
        if a.strip() in aliases:
            return aliases[a.strip()].get(src)
        m = re.fullmatch(r"(\S+)\s*(===|!==|==|!=)\s*(.+)", a.strip())
        if m:
            lhs, op, rhs = m.group(1), m.group(2), m.group(3)
            if lhs != reg and rhs.strip() == reg:
                lhs, rhs = rhs.strip(), lhs
            if lhs != reg:
                return None
            c = const(rhs)
            if c is None:
                return None
            if c[0] == "name":
                eq = (c[1] == src) if (sv is None or values.get(c[1]) is None) \
                    else values[c[1]] == sv
            elif sv is None:
                return None
            else:
                eq = c[1] == sv
            return eq if op in ("==", "===") else not eq
        m = re.fullmatch(rf"{re.escape(reg)}\s*\[\s*(\d+)\s*\]", a.strip())
        if m and sv is not None:
            return bool((sv >> int(m.group(1))) & 1)
        return None

    try:
        p = _Parser(_tokens(guard), atom)
        res = p.p_or()
        if p.peek() is not None:
            raise ValueError("trailing tokens")
    except (ValueError, IndexError):
        return None, False
    if not p.hit:
        return guard, False
    return res, True


# ------------------------------------------------------------------ state-derived wire aliases
_DECL = re.compile(r"\b(?:wire|logic|bit)\b\s*(?:signed\s*)?(?:\[[^\]]*\]\s*)?"
                   r"([A-Za-z_]\w*)\s*=\s*([^;]+);")
_ASSIGN = re.compile(r"\bassign\s+([A-Za-z_]\w*)\s*=\s*([^;]+);")
_DEFINE = re.compile(r"`define[ \t]+([A-Za-z_]\w*)[ \t]+([^\n]+)")


def _expand_macros(text: str, macros: dict[str, str]) -> str:
    for _ in range(4):  # nested macros
        new = re.sub(r"`([A-Za-z_]\w*)", lambda m: macros.get(m.group(1), m.group(0)), text)
        if new == text:
            break
        text = new
    return text


def _alias_defs(path: str, module: str) -> dict[str, tuple[str, str, int]]:
    """{name: (rhs with `define macros expanded, rhs as written, line)} for every wire of `module`
    in `path` that has exactly one continuous assignment."""
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    fp = x4_tools.x4("fsm_prove")
    txt = fp.mask_comments(raw)
    loc = fp.find_module({path: txt}, module)
    if not loc:
        return {}
    macros = {k: v.strip() for k, v in _DEFINE.findall(txt)}
    body, off = txt[loc[1]:loc[2]], loc[1]
    found: dict[str, list] = {}
    for rx in (_DECL, _ASSIGN):
        for m in rx.finditer(body):
            rhs = " ".join(m.group(2).split())
            line = txt.count("\n", 0, off + m.start()) + 1
            found.setdefault(m.group(1), []).append((_expand_macros(rhs, macros), rhs, line))
    return {n: v[0] for n, v in found.items() if len(v) == 1}


def state_aliases(f: dict, extra: dict, values: dict[str, int | None],
                  simp: list) -> dict[str, dict[str, bool]]:
    """Wires that are pure functions of the state register, e.g. `wire on_e = (pos == `E);`
    (S1_sequence_detector): {name: {state: bool}}. Only wires used in a transition guard are
    evaluated; each one used is a simplification row. Needs extra.file (none without e8)."""
    if not extra.get("file"):
        return {}
    conds = " ".join(str(t.get("cond") or "") for t in f.get("transitions", []))
    defs = {n: d for n, d in _alias_defs(str(extra["file"]), f["module"]).items()
            if n != f.get("state") and re.search(rf"(?<![\w`$]){re.escape(n)}(?![\w])", conds)}
    out: dict[str, dict[str, bool]] = {}
    for _ in range(3):  # aliases of aliases
        for n, (rhs, _, _) in defs.items():
            if n in out:
                continue
            per = {s: specialise(rhs, f.get("state"), s, values, out)[0] for s in values}
            if per and all(isinstance(v, bool) for v in per.values()):
                out[n] = per
    for n in out:
        rhs_written, line = defs[n][1], defs[n][2]
        true_in = sorted(s for s, v in out[n].items() if v)
        simp.append({"what": f"wire alias '{n} = {rhs_written}' evaluated per state",
                     "reason": f"'{n}' is a function of the state register only (true in "
                               f"{true_in}); guards specialised through it",
                     "lines": [{"file": str(extra["file"]), "line": line}]})
    return out


# ------------------------------------------------------------------ helpers


def _kind(guard: str, semantic: bool) -> str:
    if guard.strip() == "1":
        return "always"
    if DATAPATH in guard:
        return "unknown"
    return "cube" if semantic else "expr"


def _sid(name: str) -> str:
    return "s." + re.sub(r"[^A-Za-z0-9_.$]", "_", str(name))


def _lines(extra: dict, key: str) -> list[dict]:
    out = []
    for ln in (extra.get("transition_lines") or {}).get(key, []) or []:
        if isinstance(ln, dict) and ln.get("file") and ln.get("line") is not None:
            out.append({"file": str(ln["file"]), "line": int(ln["line"])})
    return out


def _values(f: dict, extra: dict, simp: list) -> dict[str, int | None]:
    names = [s["name"] for s in f.get("states", [])]
    ev = extra.get("values")
    if isinstance(ev, dict) and ev:
        return {n: (int(ev[n]) if ev.get(n) is not None else None) for n in names}
    vals = {s["name"]: parse_literal(str(s.get("value") or "")) for s in f.get("states", [])}
    simp.append({"what": "state values parsed from fsm.json states[].value",
                 "reason": "no extra.values (fsm_ext without e8 extra); "
                           f"{sum(v is None for v in vals.values())} of {len(vals)} unknown",
                 "lines": []})
    return vals


def _sem_pairs(f: dict, values: dict[str, int | None]) -> list[tuple[str, str, str]]:
    """semantic_transitions as (src name, dst name, cond); L1 emits dicts with value strings,
    FORMATS.md shows [src, dst] name pairs; both accepted."""
    by_val = {v: n for n, v in values.items() if v is not None}

    def name(x) -> str:
        x = str(x)
        if x in values:
            return x
        v = parse_literal(x)
        return by_val.get(v, f"S_{x}") if v is not None else x

    out = []
    for t in f.get("semantic_transitions") or []:
        if isinstance(t, dict):
            out.append((name(t.get("src")), name(t.get("dst")), str(t.get("cond") or "1")))
        elif isinstance(t, (list, tuple)) and len(t) >= 2:
            out.append((name(t[0]), name(t[1]), str(t[2]) if len(t) > 2 else "1"))
    return out


def _is_reset_guard(guard: str) -> bool:
    g = guard.strip().lstrip("!~").strip().strip("()").strip().lstrip("!~").strip()
    return _RESET_NAME.fullmatch(g) is not None


class _Edges:
    """Ordered (src, dst) -> merged edge accumulator."""

    def __init__(self):
        self.d: dict[tuple[str, str], dict] = {}

    def add(self, src, dst, guard, kind, lines, seen):
        e = self.d.setdefault((src, dst), {"guards": [], "kinds": [], "lines": [], "seen": set()})
        if guard not in e["guards"]:
            e["guards"].append(guard)
            e["kinds"].append(kind)
        for ln in lines:
            if ln not in e["lines"]:
                e["lines"].append(ln)
        e["seen"] |= set(seen)


# ------------------------------------------------------------------ main conversion


def _expand_star(f, t, names, values, sem, extra, simp, edges, reset_name, aliases):
    reg, dst, guard = f.get("state"), t["dst"], str(t.get("cond") or "1")
    lines = _lines(extra, f"*->{dst}")
    if dst == reset_name and _is_reset_guard(guard):
        simp.append({"what": f"dropped '* -> {dst}' guarded by '{guard}'",
                     "reason": "reset transition: drawn as the entry arrow to the reset state",
                     "lines": lines})
        return
    if sem:
        cands = [a for a, b, _ in sem if b == dst]
        cands = list(dict.fromkeys(cands))
        how = "semantic_transitions"
        if not cands:
            cands, how = list(names), "all states (no semantic transition into dst)"
    else:
        cands, how = list(names), "all states"
    kept, pruned, unparsed = [], [], False
    for s in cands:
        res, _ = specialise(guard, reg, s, values, aliases)
        if res is None:
            unparsed = True
            kept.append((s, guard))
        elif res is False:
            pruned.append(s)
        else:
            kept.append((s, "1" if res is True else res))
    for s, gs in kept:
        edges.add(s, dst, gs, _kind(gs, False), lines or _lines(extra, f"{s}->{dst}"),
                  ["syntactic"])
    note = f"; pruned {pruned} (guard false for that state)" if pruned else ""
    note += "; guard did not parse, not specialised" if unparsed else ""
    simp.append({"what": f"expanded '* -> {dst}' to {len(kept)} source(s)",
                 "reason": f"src='*' expanded over {how}{note}; guard specialised per source "
                           "by evaluating state-register atoms and state aliases",
                 "lines": lines})


def _syntactic(f, names, values, sem, extra, simp, edges, reset_name):
    reg = f.get("state")
    aliases = state_aliases(f, extra, values, simp)
    for t in f.get("transitions", []):
        src, dst, guard = t.get("src"), t.get("dst"), str(t.get("cond") or "1")
        if src == "*":
            _expand_star(f, t, names, values, sem, extra, simp, edges, reset_name, aliases)
            continue
        lines = _lines(extra, f"{src}->{dst}")
        res, touched = specialise(guard, reg, src, values, aliases)
        if res is False:
            simp.append({"what": f"dropped {src} -> {dst} ('{guard}')",
                         "reason": "guard is false when the state register holds the source "
                                   "state", "lines": lines})
            continue
        gs = guard if not touched else ("1" if res is True else res)
        if touched and gs != guard:
            simp.append({"what": f"guard of {src} -> {dst} specialised",
                         "reason": f"state-register atoms evaluated for src={src}: "
                                   f"'{guard}' -> '{gs}'", "lines": lines})
        edges.add(src, dst, gs, _kind(gs, False), lines, ["syntactic"])


def _semantic(f, sem, extra, edges, simp, label: str, names: list[str]):
    n_new, bad = 0, []
    for a, b, cond in sem:
        if a not in names or b not in names:
            bad.append(f"{a}->{b}")
            continue
        new = (a, b) not in edges.d
        n_new += new
        edges.add(a, b, cond, _kind(cond, True), _lines(extra, f"{a}->{b}"), ["semantic"])
    if bad:
        simp.append({"what": f"dropped {len(bad)} semantic edge(s) with a non-state endpoint",
                     "reason": "endpoint value maps to no state (state values unknown, e.g. no "
                               f"extra.values): {sorted(set(bad))[:6]}", "lines": []})
    if n_new and label:
        simp.append({"what": f"{n_new} executed-only edge(s) added",
                     "reason": f"{label}: semantic_transitions has (src, dst) pairs the syntactic "
                               "extraction lacks; kept with seen_by=['semantic']", "lines": []})


def _merge(edges: _Edges, states: dict[str, dict], simp: list) -> list[dict]:
    out = []
    for (src, dst), e in edges.d.items():
        guards, kinds = e["guards"], e["kinds"]
        if len(guards) > 1:
            g = "1" if "1" in guards else " || ".join(guards)
            kind = ("always" if g == "1" else "unknown" if "unknown" in kinds
                    else "expr" if "expr" in kinds else "cube")
            simp.append({"what": f"merged {len(guards)} edges {src} -> {dst}",
                         "reason": "one transition per (src, dst): guards joined with ' || '"
                                   + (" (one guard is '1', so the union is '1')" if g == "1"
                                      else ""), "lines": e["lines"]})
        else:
            g, kind = guards[0], kinds[0]
        seen = [s for s in ("syntactic", "semantic") if s in e["seen"]]
        out.append({"id": f"t.{len(out)}", "src": states.get(src, {"id": _sid(src)})["id"],
                    "dst": states.get(dst, {"id": _sid(dst)})["id"], "guard": g,
                    "guard_kind": kind, "lines": e["lines"], "seen_by": seen})
    return out


def _encoding(extra: dict, values: dict[str, int | None]) -> str:
    enc = extra.get("encoding")
    if enc in ("binary", "onehot", "gray", "enum", "other"):
        return enc
    vs = list(values.values())
    if not vs or any(v is None for v in vs) or len(set(vs)) != len(vs):
        return "other"
    if len(vs) > 1 and all(v > 0 and v & (v - 1) == 0 for v in vs):
        return "onehot"
    return "binary"


def _states(f, extra, values, simp, reset_name: str | None) -> dict[str, dict]:
    reached = extra.get("reached")
    unnamed = extra.get("unnamed")
    if unnamed is None:
        unnamed = [s["name"] for s in f.get("states", [])
                   if re.fullmatch(r"S_\d+", s["name"]) or parse_literal(s["name"]) is not None]
        if unnamed:
            simp.append({"what": f"{len(unnamed)} state(s) flagged unnamed by name pattern",
                         "reason": "no extra.unnamed: names 'S_<v>' or plain literals treated as "
                                   "fallback names", "lines": []})
    if reached is None:
        simp.append({"what": "all states marked reached",
                     "reason": "extra.reached unknown (null or no extra)", "lines": []})
    out: dict[str, dict] = {}
    for s in f.get("states", []):
        n = s["name"]
        out[n] = {"id": _sid(n), "name": n, "value": values.get(n),
                  "reset": n == reset_name,
                  "reached": True if reached is None else n in reached,
                  "unnamed": n in unnamed}
    return out


def _seen_semantic(f, transitions, simp) -> None:
    sc = f.get("semantic_check")
    if sc == "consistent" and not f.get("semantic_transitions"):
        for t in transitions:
            if t["src"] != t["dst"] and "semantic" not in t["seen_by"]:
                t["seen_by"].append("semantic")
        simp.append({"what": "seen_by 'semantic' inferred for non-self-loop edges",
                     "reason": "semantic_check=consistent: executed graph isomorphic to the "
                               "syntactic one (self-loops excluded); no per-edge semantic list",
                     "lines": []})


def _reset_state(f: dict, simp: list) -> str | None:
    """L1 reset_state; when it is None, the dst of a `* -> X` edge guarded only by a reset
    signal (S1_fsm_hdlc: `cur <= reset ? R0 : upd`)."""
    if f.get("reset_state") is not None:
        return f["reset_state"]
    names = {s["name"] for s in f.get("states", [])}
    for t in f.get("transitions", []):
        cond = str(t.get("cond") or "")
        if t.get("src") == "*" and t.get("dst") in names and _is_reset_guard(cond):
            simp.append({"what": f"reset state inferred as {t['dst']}",
                         "reason": f"L1 reset_state is null; '* -> {t['dst']}' is guarded only by "
                                   f"the reset signal '{cond}'",
                         "lines": _lines(f.get("extra") or {}, f"*->{t['dst']}")})
            return t["dst"]
    return None


def _e8_simplifications(extra: dict) -> list[dict]:
    """extra.simplifications (e8: state renames, L1-vs-walker divergences), kept 1:1."""
    out = []
    for r in extra.get("simplifications") or []:
        if not isinstance(r, dict) or not r.get("what"):
            continue
        lines = [{"file": str(ln["file"]), "line": int(ln["line"])}
                 for ln in r.get("lines") or []
                 if isinstance(ln, dict) and ln.get("file") and ln.get("line") is not None]
        out.append({"what": str(r["what"]), "reason": str(r.get("reason") or "from e8"),
                    "lines": lines})
    return out


def build_one(design: str, f: dict) -> object:
    extra = f.get("extra") or {}
    simp: list[dict] = _e8_simplifications(extra)
    if not f.get("extra"):
        simp.append({"what": "no 'extra' block", "reason": "fsm_ext element without e8 extra: "
                     "values from fsm.json only, no source lines, reached unknown", "lines": []})
    values = _values(f, extra, simp)
    reset_name = _reset_state(f, simp)
    states = _states(f, extra, values, simp, reset_name)
    names = list(states)
    sc = f.get("semantic_check")
    sem = _sem_pairs(f, values)
    edges = _Edges()
    if f.get("style") == "semantic" or sc == "semantic-only":
        _semantic(f, [(t["src"], t["dst"], str(t.get("cond") or "1"))
                      for t in f.get("transitions", [])], extra, edges, simp, "", names)
    else:
        _syntactic(f, names, values, sem, extra, simp, edges, reset_name)
        if sem:
            _semantic(f, sem, extra, edges, simp, f"semantic_check={sc}", names)
    transitions = _merge(edges, states, simp)
    _seen_semantic(f, transitions, simp)
    g = _graph(design, f, extra, states, transitions, values, simp)
    _gate(g, f)
    return g


def _outputs(f, extra):
    if f.get("style") == "semantic" or f.get("semantic_check") == "semantic-only":
        o = extra.get("outputs_semantic")
        return None if o is None else [_out(x) for x in o]
    return [_out(x) for x in f.get("outputs") or []]


def _out(x: dict) -> dict:
    return {"signal": x["signal"], "kind": x.get("kind", "moore"), "port": bool(x.get("port"))}


def _graph(design, f, extra, states, transitions, values, simp):
    prov = extra.get("provenance") or {}
    return fsm_spec.FsmGraph(
        design=design, module=f["module"], instance=f.get("instance") or f["module"],
        state_reg=f["state"], width=extra.get("width"), encoding=_encoding(extra, values),
        file=extra.get("file"), states=list(states.values()), transitions=transitions,
        outputs=_outputs(f, extra), simplifications=simp,
        provenance={"engine": extra.get("engine", "l1-hybrid"), "style": f.get("style"),
                    "seed": prov.get("seed"), "time_budget": prov.get("time_budget"),
                    "budget_exhausted": prov.get("budget_exhausted")},
    )


def _gate(g, f) -> None:
    sc = f.get("semantic_check")
    g.checks.semantic = {"semantic_check": sc, "ok": sc in OK_SEMANTIC}
    g.checks.structural = fsm_check.structural(g)
    reasons = []
    if sc not in OK_SEMANTIC:
        warn = [w for w in f.get("warnings", []) if "semantic" in w]
        reasons.append(f"G3: semantic_check={sc}" + (f" ({warn[0]})" if warn else ""))
    if not g.checks.structural.get("ok"):
        reasons.append("G2: " + "; ".join(g.checks.structural.get("issues", [])[:4]))
    if reasons:
        g.status = "rejected"
        g.rejected_reason = " | ".join(reasons)


def build(design: str, fsm_ext: list[dict]) -> list:
    """One FsmGraph per FSM element of `fsm_ext` (status ok | rejected, never dropped)."""
    return [build_one(design, f) for f in fsm_ext]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fsm_ext")
    ap.add_argument("--design", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    p = Path(a.fsm_ext)
    design = a.design or p.parent.name
    out = Path(a.out) if a.out else p.parent / "fsm"
    out.mkdir(parents=True, exist_ok=True)
    for g in build(design, json.loads(p.read_text(encoding="utf-8"))):
        q = out / f"{g.module}.{g.state_reg}.json"
        q.write_text(g.model_dump_json(indent=1), encoding="utf-8")
        print(f"{q}  {g.status}  {len(g.states)} states  {len(g.transitions)} transitions"
              + (f"  ({g.rejected_reason})" if g.rejected_reason else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
