"""x4 timing L2 stand-in: signals.json + graph.json + sim.json + VCD -> TimingDiagram v0.1 list.

    uv run python pipeline/experiments/x4_fsm_timing/timing_bridge.py DIR [--fsm-ext F] [--out O]

DIR holds signals.json, graph.json, sim.json (its "vcd" path is used; a relative path is taken
from the repo root, else DIR/wave.vcd). Prints a summary and writes <O>/<id>.json when --out.

Rules (plan §3 Stage 2; every one is also recorded in the diagram's `simplifications`):
- samples: each lane is sampled at its own domain's posedges with vcd.Vcd.at (last change
  strictly before the edge); events only count after reset release. Interface members missing
  from the VCD or without a simulated clock domain are dropped; an interface whose handshake
  members are all gone is skipped (design-level note), never drawn from internal lanes alone.
- events are detected per anchor in the anchor member's own domain (a two-clock FIFO's wr side on
  the write clock, rd side on the read clock). Scenarios per interface (<= 3): first-fire,
  first-stall (valid high, ready low, then fire without valid dropping), back-to-back (fire in
  two consecutive cycles); each anchor adds its own window to a scenario. FSM state registers of
  the top module (fsm_ext) give one extra "fsm" scenario (reset release + first occurrence of
  every state transition; skipped when no transition follows reset release).
  Window = [event-2, event+3] cycles of the event's domain; overlapping or touching windows merge.
- one diagram per contiguous span: a window joins the previous span only when no drawn lane
  changes between them (the stretch becomes ordinary idle gaps); otherwise it becomes its own
  diagram "<id>.w2", "<id>.w3", ... No gap ever hides a change.
- lanes: interface members (handshake first, data as bus), <= 4 internal lanes near the
  interface, FSM state lanes; <= 12 lanes, <= 30 drawn fastest-domain cycles (a span longer than
  that is trimmed at its end, recorded).
- gaps: a run of > 2 fastest-domain cycles in which no drawn lane in any domain changes keeps its
  first cycle and hides the rest (exact per-domain posedge counts).
- arrows: sources are handshake/control/state lanes, plus register (is_state) lanes for cdc.
  same-cycle = path with 0 is_state nodes after the source, next-cycle = exactly 1; cdc = a path
  across domains through a register pair (>= 1 source-domain register, the source included,
  then >= 1 destination-domain register, the destination included; register domains from graph
  CLOCK edges), <= 4 registers after the source, every VCD-visible hop and the destination
  changing at its exact sampled cycle (cdc_cycle); among consistent paths the one with the most
  registers wins (L1 adds shortcut edges across synchronizer chains); absolute t; each
  destination change keeps only its latest source change. Graph search is a BFS over
  DATA/CONTROL/ADDR/PORT edges without fan-in pruning; every VCD-visible node on the path must
  change at its cycle.
  A next-cycle path through an FSM state register (fsm_ext) is kept only if it passes through a
  signal read by the guard of the transition actually taken (src state at c -> state at c+1);
  such an FSM-explained path is preferred over a shorter path through another register.
  Rejected candidates are counted in the simplifications. More than 6 arrows touching one
  time point (as source or destination) split the diagram into parts (".p2", ...).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shlex
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def _sibling(name: str):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


x4_tools = _sibling("x4_tools")
ts = x4_tools.x4("timing_spec")
vcdmod = x4_tools.x4("vcd")

MAX_LANES = 12
MAX_CYCLES = 30
MAX_ARROWS_PER_CYCLE = 6
MAX_INTERNAL = 4
MAX_CDC_REGS = 4  # source register + 2-flop synchronizer + destination register
PRE, POST = 2, 3
PATH_TYPES = ("DATA", "CONTROL", "ADDR", "PORT")
HANDSHAKE = ("valid", "ready", "req", "ack", "wr", "rd", "we", "enable", "full", "empty",
             "tick", "serial")
DATAROLES = ("addr", "data", "wdata", "rdata")
SOURCE_ROLES = frozenset((*HANDSHAKE, "state"))
ANCHOR_ROLES = ("valid", "req", "ack", "wr", "rd", "we", "enable", "tick")
RTL_EXT = (".v", ".sv", ".vh", ".svh")
_VIA_LINE = re.compile(r"@L(\d+)")
_IDENT = re.compile(r"(?<![\w$'])[A-Za-z_][\w$]*")
_MODULE = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.M)


# ---- context ------------------------------------------------------------------------------
@dataclass
class Clock:
    dom: str
    port: str
    period: int
    phase: int
    edges: list[int]


@dataclass
class LaneSpec:
    signal: str
    width: int
    role: str
    dom: str
    line: int | None
    prio: int  # 0 handshake, 1 fsm state, 2 data, 3 internal, 4 reset
    interface: str | None = None
    enum: dict[str, str] | None = None
    key: str | None = None


@dataclass
class FsmInfo:
    key: str
    signal: str
    dom: str
    enum: dict[str, str]  # sampled value -> state name
    trans: list[tuple[str, str, str]]  # (src state, dst state, guard text)


@dataclass
class Anchor:
    label: str
    dom: str
    fire: list[bool]
    stall: list[bool] | None


@dataclass
class Ctx:
    design: str
    top: str
    inst: str
    dut: str
    graph: dict
    sim: dict
    vcd: object
    clocks: dict[str, Clock]
    fastest: str
    files: list[str]
    reset_t: int
    log: list[dict] = field(default_factory=list)
    mod2file: dict[str, str] = field(default_factory=dict)
    fsms: dict[str, FsmInfo] = field(default_factory=dict)
    port2dom: dict[str, str] = field(default_factory=dict)
    _cache: dict = field(default_factory=dict)

    def hier(self, signal: str) -> str:
        return f"{self.dut}.{signal}"

    def node_key(self, signal: str) -> str | None:
        k = f"{self.inst}.{signal}"
        return k if k in self.graph["nodes"] else None

    def file_of(self, key: str | None) -> str:
        node = self.graph["nodes"].get(key or "", {})
        return (node.get("file") or self.mod2file.get(node.get("module") or self.top)
                or (self.files[0] if self.files else "<unknown>"))

    def samples(self, signal: str, dom: str) -> list[str]:
        """Value at every posedge of `dom` (cached)."""
        ck = (signal, dom)
        if ck not in self._cache:
            name = self.hier(signal)
            self._cache[ck] = [self.vcd.at(name, t) for t in self.clocks[dom].edges]
        return self._cache[ck]

    def cycle_after(self, dom: str, t: int) -> int:
        """Index of the first posedge of `dom` strictly after t."""
        for i, e in enumerate(self.clocks[dom].edges):
            if e > t:
                return i
        return len(self.clocks[dom].edges)


def _rtl_files(graph: dict, sim: dict, fsm_ext: list[dict] | None) -> list[str]:
    """RTL sources: graph["files"], fsm_ext extra.file, then RTL arguments of sim.json cmd."""
    files = [str(f) for f in graph.get("files") or []]
    files += [str((f.get("extra") or {})["file"]) for f in fsm_ext or []
              if (f.get("extra") or {}).get("file")]
    tb = Path(str(sim.get("tb_path") or "")).name
    for cmd in sim.get("cmd") or []:
        for arg in cmd if isinstance(cmd, list) else shlex.split(str(cmd)):
            p = Path(str(arg))
            if p.suffix not in RTL_EXT or p.name == tb:
                continue
            hit = next((c for c in (p, ROOT / p) if c.is_file()), None)
            if hit is not None:
                files.append(str(hit.resolve()))
    return list(dict.fromkeys(files))


def _module_files(files: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in files:
        try:
            text = Path(f).read_text(errors="replace")
        except OSError:
            continue
        for m in _MODULE.finditer(text):
            out.setdefault(m.group(1), f)
    return out


def _context(design: str, signals: dict, graph: dict, sim: dict, vcd, files: list[str]) -> Ctx:
    top = signals.get("top") or graph["tops"][0]
    inst = next((p for p in graph["tops"] if graph["instances"][p]["module"] == top),
                graph["tops"][0])
    dut = sim.get("dut_path") or "tb.dut"
    clocks: dict[str, Clock] = {}
    notes: list[dict] = []
    for c in sim.get("clocks", []):
        edges = vcd.posedges(f"{dut}.{c['port']}") if vcd.has(f"{dut}.{c['port']}") else []
        if len(edges) < 2:
            notes.append({"what": f"clock {c['port']} ({c['domain']})",
                          "reason": f"{len(edges)} posedge(s) in the VCD; domain not drawn"})
            continue
        clocks[c["domain"]] = Clock(c["domain"], c["port"], int(c["period"]),
                                    int(c.get("phase", 0)), edges)
    if not clocks:
        raise ValueError(f"no clock of sim.json toggles in the VCD under {dut}: {notes}")
    fastest = min(sorted(clocks), key=lambda d: clocks[d].period)
    rel = [int(r["release_t"]) for r in sim.get("resets", []) if r.get("release_t") is not None]
    ctx = Ctx(design, top, inst, dut, graph, sim, vcd, clocks, fastest, files,
              max(rel) if rel else 0, notes, _module_files(files),
              port2dom={c["port"]: c["domain"] for c in signals.get("clocks", [])})
    for c in clocks.values():
        if len(c.edges) >= 2 and c.edges[1] - c.edges[0] != c.period:
            ctx.log.append({"what": f"clock {c.port}", "reason": f"VCD period "
                            f"{c.edges[1] - c.edges[0]} != sim.json period {c.period}"})
    return ctx


# ---- lanes --------------------------------------------------------------------------------
def _width(x) -> int:
    try:
        return max(int(x), 1)
    except (TypeError, ValueError):
        return 1


def _member_lanes(ctx: Ctx, iface: dict) -> list[LaneSpec]:
    out = []
    for m in iface.get("members", []):
        role = m.get("role", "data")
        prio = 0 if role in HANDSHAKE else 2
        out.append(LaneSpec(m["port"], _width(m.get("width")), role,
                            m.get("domain") or iface.get("domain"), m.get("line"), prio,
                            iface["name"], key=ctx.node_key(m["port"])))
    order = {r: i for i, r in enumerate((*HANDSHAKE, *DATAROLES))}
    return sorted(out, key=lambda s: (s.prio, order.get(s.role, 99)))


def register_domains(graph: dict, port2dom: dict[str, str]) -> dict[str, str]:
    """register key -> clock domain: the CLOCK-edge source, followed back through <= 3 driver
    edges (e.g. `assign wclk = i_wclk`) to a clock port of `port2dom`. Shared with T2."""
    drv: dict[str, list[str]] = {}
    for e in graph["edges"]:
        if e["type"] in ("DATA", "PORT"):
            drv.setdefault(e["dst"], []).append(e["src"])

    def root(k: str) -> str | None:
        seen, front = {k}, [k]
        for _ in range(4):
            names = [graph["nodes"].get(n, {}).get("name") for n in front]
            hit = sorted({port2dom[m] for m in names if m in port2dom})
            if hit:
                return hit[0] if len(hit) == 1 else None
            front = sorted({s for n in front for s in drv.get(n, [])} - seen)
            seen |= set(front)
        return None

    out: dict[str, str] = {}
    for e in sorted(graph["edges"], key=lambda e: (e["dst"], e["src"])):
        if e["type"] == "CLOCK" and e["dst"] not in out:
            dom = root(e["src"])
            if dom is not None:
                out[e["dst"]] = dom
    return out


def _domain_of_key(ctx: Ctx, key: str) -> str | None:
    """Clock domain of a register (see register_domains)."""
    if "regdom" not in ctx._cache:
        ctx._cache["regdom"] = register_domains(ctx.graph, ctx.port2dom)
    return ctx._cache["regdom"].get(key)


def _enum(values: dict, width: int) -> dict[str, str]:
    out = {}
    for name, v in sorted(values.items(), key=lambda kv: str(kv[1])):
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        out[format(iv, "x") if width > 1 else str(iv)] = name
    return out


def _fsm_lanes(ctx: Ctx, signals: dict, fsm_ext: list[dict] | None) -> list[LaneSpec]:
    """FSM state lanes of the top instance; also fills ctx.fsms (enum + transitions)."""
    out = []
    for f in fsm_ext or []:
        ex = f.get("extra") or {}
        key = ex.get("graph_key") or f"{f.get('instance')}.{f.get('state')}"
        node = ctx.graph["nodes"].get(key)
        if f.get("module") != ctx.top or node is None or node.get("inst") != ctx.inst:
            ctx.log.append({"what": f"fsm {f.get('module')}.{f.get('state')}",
                            "reason": "not a state register of the top module instance"})
            continue
        width = _width(ex.get("width") or node.get("width"))
        enum = _enum(ex.get("values") or {}, width)
        dom = _domain_of_key(ctx, key)
        if dom is None:
            dom = ctx.fastest
            ctx.log.append({"what": f"fsm {key} domain", "reason": f"no CLOCK edge into the "
                            f"register in graph.json; assumed fastest domain {dom}"})
        signal = key[len(ctx.inst) + 1:]
        trans = [(str(t.get("src")), str(t.get("dst")), str(t.get("cond") or ""))
                 for t in f.get("transitions") or []]
        ctx.fsms[key] = FsmInfo(key, signal, dom, enum, trans)
        out.append(LaneSpec(signal, width, "state", dom, ex.get("decl_line") or
                            node.get("line"), 1, None, enum or None, key))
    return out


def _internal_lanes(ctx: Ctx, signals: dict, iface_id: str | None) -> list[LaneSpec]:
    out = []
    for s in signals.get("internal", []):
        if iface_id is not None and iface_id not in (s.get("near") or []):
            continue
        role = "state" if s.get("role") == "state" else "reg"
        out.append(LaneSpec(s["signal"], _width(s.get("width")), role, s.get("domain"),
                            s.get("line"), 3, None, key=s.get("key") or ctx.node_key(s["signal"])))
    return out


def _cap_lanes(ctx: Ctx, cands: list[LaneSpec]) -> tuple[list[LaneSpec], list]:
    """Dedupe, drop lanes absent from the VCD/clock set, keep <= 4 internal and <= 12 total."""
    simp, seen, ok = [], set(), []
    for ln in cands:
        if ln.signal in seen:
            continue
        seen.add(ln.signal)
        why = None
        if not ctx.vcd.has(ctx.hier(ln.signal)):
            why = f"{ctx.hier(ln.signal)} not in the VCD"
        elif ln.dom not in ctx.clocks:
            why = f"domain {ln.dom} has no simulated clock"
        if why:
            simp.append(_drop(ctx, ln, why))
            continue
        vw = ctx.vcd.width(ctx.hier(ln.signal))
        if vw != ln.width:
            simp.append(ts.Simplification(what=f"lane {ln.signal} width {ln.width} -> {vw}",
                                          reason="VCD declared width differs; VCD wins",
                                          lines=_lines(ctx, ln)))
            ln.width = vw
        ok.append(ln)
    internal = [ln for ln in ok if ln.prio == 3]
    for ln in internal[MAX_INTERNAL:]:
        simp.append(_drop(ctx, ln, f"more than {MAX_INTERNAL} internal lanes near the interface"))
        ok.remove(ln)
    by_prio = sorted(ok, key=lambda s: s.prio)
    for ln in by_prio[MAX_LANES:]:
        simp.append(_drop(ctx, ln, f"lane cap {MAX_LANES}"))
        ok.remove(ln)
    return ok, simp


def _lines(ctx: Ctx, ln: LaneSpec) -> list:
    if not ln.line:
        return []
    return [ts.SrcLine(file=ctx.file_of(ln.key), line=int(ln.line))]


def _drop(ctx: Ctx, ln: LaneSpec, why: str):
    return ts.Simplification(what=f"lane {ln.signal} dropped", reason=why, lines=_lines(ctx, ln))


def _usable(ctx: Ctx, iface: dict) -> tuple[dict | None, str]:
    """Interface restricted to members present in the VCD with a simulated clock domain (each
    member's "domain" resolved); None + reason when nothing drawable is left."""
    keep, lost = [], []
    for m in iface.get("members", []):
        dom = m.get("domain") or iface.get("domain")
        if dom in ctx.clocks and ctx.vcd.has(ctx.hier(m["port"])):
            keep.append({**m, "domain": dom})
        else:
            lost.append(m["port"])
    if not keep:
        return None, f"no member in the VCD with a simulated clock domain (lost {lost})"
    for roles in (HANDSHAKE, ANCHOR_ROLES):
        had = [m["port"] for m in iface.get("members", []) if m.get("role") in roles]
        if had and not any(m.get("role") in roles for m in keep):
            return None, (f"member(s) {had} (roles {'/'.join(roles[:4])}...) missing from the "
                          "VCD or without a simulated clock domain")
    return {**iface, "members": keep}, ""


# ---- events and scenarios -----------------------------------------------------------------
def _bits(vals: list[str], want: str = "1") -> list[bool]:
    return [v == want for v in vals]


def _both(a: list[bool], b: list[bool]) -> list[bool]:
    return [x and y for x, y in zip(a, b, strict=True)]


def _anchors(ctx: Ctx, iface: dict) -> list[Anchor]:
    """Handshake anchors, each sampled in its own member's domain (members already resolved)."""
    mem = {m["role"]: m for m in iface.get("members", []) if "role" in m}

    def s(role: str, dom: str, want: str = "1") -> list[bool]:
        return _bits(ctx.samples(mem[role]["port"], dom), want)

    out = []
    if "valid" in mem:
        dom, v = mem["valid"]["domain"], mem["valid"]["port"]
        if "ready" in mem:
            if mem["ready"]["domain"] != dom:
                ctx.log.append({"what": f"interface {iface['name']}", "reason": f"ready in "
                                f"{mem['ready']['domain']}, valid in {dom}; sampled in {dom}"})
            r = mem["ready"]["port"]
            vv = s("valid", dom)
            out.append(Anchor(f"{v} && {r}", dom, _both(vv, s("ready", dom)),
                              _both(vv, s("ready", dom, "0"))))
        else:
            out.append(Anchor(v, dom, s("valid", dom), None))
    for side, guard in (("wr", "full"), ("rd", "empty")):
        if side not in mem:
            continue
        dom = mem[side]["domain"]
        g = guard in mem and mem[guard]["domain"] == dom
        fire = _both(s(side, dom), s(guard, dom, "0")) if g else s(side, dom)
        stall = _both(s(side, dom), s(guard, dom)) if g else None
        out.append(Anchor(mem[side]["port"], dom, fire, stall))
    if not out:
        for role in ("we", "enable", "tick"):
            if role in mem:
                dom = mem[role]["domain"]
                out.append(Anchor(mem[role]["port"], dom, s(role, dom), None))
    return out


def _edges_of(vals: list[str]) -> list[bool]:
    return [i > 0 and vals[i - 1] in "01" and vals[i] in "01" and vals[i] != vals[i - 1]
            for i in range(len(vals))]


def _rise(vals: list[str]) -> list[bool]:
    return [i > 0 and vals[i - 1] == "0" and vals[i] == "1" for i in range(len(vals))]


def _win(ctx: Ctx, dom: str, c0: int, c1: int, reason: str) -> tuple[int, int, str]:
    e = ctx.clocks[dom].edges
    return e[max(c0, 0)], e[min(c1, len(e) - 1)], reason


def _scenarios(ctx: Ctx, iface: dict) -> list[tuple[str, list]]:
    """[(scenario, windows)]; each anchor contributes its own window, in its own domain."""
    if iface.get("protocol") == "REQ_ACK":
        return _req_ack(ctx, iface)
    anchors = _anchors(ctx, iface)
    if not anchors:
        return _first_change(ctx, iface)
    first, stall, b2b = [], [], []
    for an in anchors:
        start, n, dn = ctx.cycle_after(an.dom, ctx.reset_t), len(an.fire), an.dom
        c = next((i for i in range(start, n) if an.fire[i]), None)
        if c is not None:
            first.append(_win(ctx, dn, c - PRE, c + POST,
                              f"first fire of {an.label} at {dn} cycle {c}"))
        st = _first_stall(an, start)
        if st:
            s0, f = st
            stall += [_win(ctx, dn, s0 - PRE, s0 + POST,
                           f"stall starts: {an.label} pending at {dn} cycle {s0}"),
                      _win(ctx, dn, f - PRE, f + POST,
                           f"{an.label} fires after {f - s0}-cycle stall at {dn} cycle {f}")]
        c = next((i for i in range(start, n - 1) if an.fire[i] and an.fire[i + 1]), None)
        if c is not None:
            b2b.append(_win(ctx, dn, c - PRE, c + 1 + POST,
                            f"{an.label} fires at {dn} cycles {c} and {c + 1}"))
    return [(name, w) for name, w in (("first-fire", first), ("first-stall", stall),
                                      ("back-to-back", b2b)) if w]


def _first_change(ctx: Ctx, iface: dict) -> list:
    """SERIAL / MEMORY_BUS without enables: first change of the first 1-bit member."""
    for m in iface.get("members", []):
        if _width(m.get("width")) == 1:
            dom = m["domain"]
            ch = _edges_of(ctx.samples(m["port"], dom))
            start = ctx.cycle_after(dom, ctx.reset_t)
            c = next((i for i in range(start, len(ch)) if ch[i]), None)
            if c is None:
                return []
            return [("first-fire", [_win(ctx, dom, c - PRE, c + POST,
                                         f"first change of {m['port']} at {dom} cycle {c}")])]
    return []


def _first_stall(an: Anchor, start: int):
    if an.stall is None:
        return None
    n = len(an.fire)
    for s0 in range(start, n):
        if not an.stall[s0] or (s0 > 0 and an.stall[s0 - 1]):
            continue
        f = s0
        while f < n and an.stall[f]:
            f += 1
        if f < n and an.fire[f]:
            return s0, f
    return None


def _req_ack(ctx: Ctx, iface: dict) -> list:
    """req rise in req's domain, then the first ack rise at or after it in ack's domain."""
    mem = {m["role"]: m for m in iface.get("members", [])}
    if "req" not in mem or "ack" not in mem:
        return []
    dq, da = mem["req"]["domain"], mem["ack"]["domain"]
    rq = _rise(ctx.samples(mem["req"]["port"], dq))
    ak = _rise(ctx.samples(mem["ack"]["port"], da))
    c = next((i for i in range(ctx.cycle_after(dq, ctx.reset_t), len(rq)) if rq[i]), None)
    if c is None:
        return []
    wins = [_win(ctx, dq, c - PRE, c + POST,
                 f"first rising {mem['req']['port']} at {dq} cycle {c}")]
    a0 = ctx.cycle_after(da, ctx.clocks[dq].edges[c] - 1)
    a = next((i for i in range(a0, len(ak)) if ak[i]), None)
    if a is not None:
        wins.append(_win(ctx, da, a - PRE, a + POST,
                         f"rising {mem['ack']['port']} at {da} cycle {a}"))
    return [("first-fire", wins)]


def _fsm_scenario(ctx: Ctx, ln: LaneSpec) -> list:
    """Reset release + first occurrence of every transition; [] when no transition follows."""
    dom = ln.dom
    vals = ctx.samples(ln.signal, dom)
    start = ctx.cycle_after(dom, ctx.reset_t)
    if start >= len(vals):
        return []
    wins = [_win(ctx, dom, start - PRE, start + POST, f"reset release at t={ctx.reset_t}")]
    seen = set()
    name = ln.enum or {}
    for c in range(max(start, 1), len(vals)):
        a, b = vals[c - 1], vals[c]
        if a != b and (a, b) not in seen and "x" not in (a + b):
            seen.add((a, b))
            wins.append(_win(ctx, dom, c - PRE, c + POST,
                             f"{ln.signal} {name.get(a, a)} -> {name.get(b, b)} at cycle {c}"))
    return wins if seen else []


# ---- windows, spans, gaps -----------------------------------------------------------------
def _merge(ctx: Ctx, wins: list) -> list[tuple[int, int, str, list]]:
    """Merge overlapping/touching windows; each result carries its merge simplifications."""
    fast = ctx.clocks[ctx.fastest].edges
    out: list[tuple[int, int, str, list]] = []
    for t0, t1, why in sorted(wins):
        if out and (t0 <= out[-1][1] or not any(out[-1][1] < e < t0 for e in fast)):
            p0, p1, pw, ps = out[-1]
            ps = [*ps, ts.Simplification(what=f"windows merged: [{p0},{p1}] + [{t0},{t1}]",
                                         reason="overlapping or adjacent windows of one "
                                                "scenario")]
            out[-1] = (p0, max(p1, t1), f"{pw}; {why}", ps)
        else:
            out.append((t0, t1, why, []))
    return out


def _change_times(ctx: Ctx, lanes: list[LaneSpec], lo: int, hi: int) -> list[int]:
    out = set()
    for ln in lanes:
        e = ctx.clocks[ln.dom].edges
        vals = ctx.samples(ln.signal, ln.dom)
        for i in range(1, len(e)):
            if lo <= e[i] <= hi and vals[i] != vals[i - 1]:
                out.add(e[i])
    return sorted(out)


def _idle_gaps(ctx: Ctx, lanes: list[LaneSpec], t0: int, t1: int) -> list[tuple[int, int]]:
    """(after_t, until_t) gaps inside one window: hide cycles h+1..g of every maximal run h..g
    (length > 2) of fastest-domain cycles whose open neighbourhood (F[k-1], F[k+1]) has no
    change; the cycle after the run is drawn."""
    f = [e for e in ctx.clocks[ctx.fastest].edges if t0 <= e <= t1]
    ch = _change_times(ctx, lanes, t0, t1)

    def quiet(k: int) -> bool:
        return not any(f[k - 1] < t < f[k + 1] for t in ch)

    gaps, k = [], 1
    while k < len(f) - 1:
        if not quiet(k):
            k += 1
            continue
        g = k
        while g + 1 < len(f) - 1 and quiet(g + 1):
            g += 1
        if g - k + 1 > 2:
            gaps.append((f[k], f[g + 1]))
        k = g + 1
    return gaps


def _count(edges: list[int], lo: int, hi: int) -> int:
    return sum(1 for e in edges if lo < e < hi)


def _drawn(ctx: Ctx, dom: str, win: tuple, gaps: list) -> list[int]:
    e = ctx.clocks[dom].edges
    return [i for i, t in enumerate(e)
            if win[0] <= t <= win[1] and not any(a < t < b for a, b in gaps)]


def _n_fast(ctx: Ctx, lanes: list[LaneSpec], win: tuple) -> int:
    return len(_drawn(ctx, ctx.fastest, win, _idle_gaps(ctx, lanes, win[0], win[1])))


def _spans(ctx: Ctx, lanes: list[LaneSpec], wins: list) -> list[tuple[tuple, list]]:
    """Contiguous spans [(window, simplifications)]: a merged window joins the previous span
    only when no drawn lane changes strictly between them and the cap still holds."""
    spans: list[list] = []
    for t0, t1, why, simp in _merge(ctx, wins):
        if spans:
            p0, p1, pw = spans[-1][0]
            cand = (p0, t1, f"{pw}; {why}")
            if not _change_times(ctx, lanes, p1 + 1, t0 - 1) and \
                    _n_fast(ctx, lanes, cand) <= MAX_CYCLES:
                spans[-1][0] = cand
                spans[-1][1] += [*simp, ts.Simplification(
                    what=f"windows joined: [{p0},{p1}] + [{t0},{t1}]",
                    reason="no drawn lane changes between them; the stretch is drawn or "
                           "shown as idle gaps")]
                continue
        spans.append([(t0, t1, why), list(simp)])
    return [(_trim(ctx, lanes, w, s), s) for w, s in spans]


def _trim(ctx: Ctx, lanes: list[LaneSpec], win: tuple, simp: list) -> tuple:
    """Trim the end of a span until <= MAX_CYCLES fastest cycles are drawn (recorded)."""
    t0, t1, why = win
    n0 = _n_fast(ctx, lanes, win)
    while _n_fast(ctx, lanes, (t0, t1, why)) > MAX_CYCLES:
        t1 = [x for x in ctx.clocks[ctx.fastest].edges if t0 <= x < t1][-1]
    if t1 != win[1]:
        simp.append(ts.Simplification(what=f"window [{t0},{win[1]}] trimmed to end at {t1}",
                                      reason=f"{n0} drawn cycles > cap {MAX_CYCLES}"))
    return t0, t1, why


# ---- arrows -------------------------------------------------------------------------------
def _adj(ctx: Ctx) -> dict[str, list[tuple[str, str]]]:
    if "adj" not in ctx._cache:
        adj: dict[str, list[tuple[str, str]]] = {}
        order = {t: i for i, t in enumerate(PATH_TYPES)}
        for e in sorted(ctx.graph["edges"], key=lambda e: (e["src"], e["dst"],
                                                           order.get(e["type"], 9), e["via"])):
            if e["type"] in PATH_TYPES and e["src"] != e["dst"]:
                adj.setdefault(e["src"], []).append((e["dst"], e["via"]))
        ctx._cache["adj"] = adj
    return ctx._cache["adj"]


def find_path(graph: dict, adj: dict, src: str, dst: str, regs: int, ok=None):
    """Shortest path src -> dst whose nodes after src contain exactly `regs` is_state nodes.
    `ok(node, r)` (optional) must accept every intermediate node, r = registers so far.
    Returns (nodes, vias) or None. No fan-in pruning; deterministic (sorted adjacency)."""
    nodes = graph["nodes"]
    start = (src, 0)
    prev: dict[tuple[str, int], tuple[tuple[str, int], str] | None] = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        node, r = cur
        if node == dst and r == regs and cur != start:
            return _unwind(prev, cur)
        for nxt, via in adj.get(node, []):
            r2 = r + (1 if nodes.get(nxt, {}).get("is_state") else 0)
            st = (nxt, r2)
            if r2 > regs or st in prev or (nxt == src):
                continue
            if ok is not None and nxt != dst and not ok(nxt, r2):
                continue
            prev[st] = (cur, via)
            q.append(st)
    return None


def _unwind(prev, cur):
    path, vias = [cur[0]], []
    while prev[cur] is not None:
        cur, via = prev[cur]
        path.append(cur[0])
        vias.append(via)
    return path[::-1], vias[::-1]


def _via_lines(ctx: Ctx, path: list[str], vias: list[str]) -> list:
    out, seen = [], set()
    for dst, via in zip(path[1:], vias, strict=True):
        m = _VIA_LINE.search(via)
        if not m:
            continue
        sl = (ctx.file_of(dst), int(m.group(1)))
        if sl not in seen:
            seen.add(sl)
            out.append(ts.SrcLine(file=sl[0], line=sl[1]))
    return out


def _visible_changes(ctx: Ctx, ln: LaneSpec, drawn: list[int]) -> set[int]:
    """Drawn cycles where the lane really changes and the previous drawn sample differs."""
    vals = ctx.samples(ln.signal, ln.dom)
    out = set()
    for j, c in enumerate(drawn):
        if j and c > 0 and vals[c] != vals[c - 1] and vals[c] != vals[drawn[j - 1]]:
            out.add(c)
    return out


@dataclass
class ArrowLog:
    rejected: list[str] = field(default_factory=list)  # FSM guard does not read the source
    unverified: list[tuple[str, str]] = field(default_factory=list)  # (end pair, fsm key)
    cdc_dropped: list[str] = field(default_factory=list)  # later repeats of a cdc lane pair


def _arrows(ctx: Ctx, lanes: list[tuple[str, LaneSpec]], drawn: dict[str, list[int]]):
    adj = _adj(ctx)
    ch = {lid: _visible_changes(ctx, ln, drawn[ln.dom]) for lid, ln in lanes}
    found, alog = [], ArrowLog()
    for aid, a in lanes:
        if a.key is None:
            continue
        for bid, b in lanes:
            if bid == aid or b.key is None:
                continue
            found += _pair_arrows(ctx, adj, (aid, a), (bid, b), ch, alog)
    found.sort(key=lambda x: (x[0].t, x[1].t, x[0].lane, x[1].lane))
    out = []
    for i, (s, d, regs, kind, path, vias) in enumerate(found, 1):
        out.append(ts.Arrow(id=f"a.{i}", src=s, dst=d, regs=regs, kind=kind, path=path,
                            via_lines=_via_lines(ctx, path, vias)))
    return out, alog


def _pair_arrows(ctx: Ctx, adj, aa, bb, ch, alog: ArrowLog) -> list:
    (aid, a), (bid, b) = aa, bb
    ea, eb = ctx.clocks[a.dom].edges, ctx.clocks[b.dom].edges
    out = []
    if a.dom == b.dom:
        if a.role not in SOURCE_ROLES:
            return out
        for c in sorted(ch[aid]):
            if c in ch[bid]:
                p = _path(ctx, adj, a.key, b.key, 0, a.dom, c)
                if p is not None:
                    out.append((ts.End(lane=aid, cycle=c, t=ea[c]),
                                ts.End(lane=bid, cycle=c, t=eb[c]), 0, "same", *p))
            if c + 1 in ch[bid]:
                p = _next_path(ctx, adj, a, b, c, alog)
                if p is not None:
                    out.append((ts.End(lane=aid, cycle=c, t=ea[c]),
                                ts.End(lane=bid, cycle=c + 1, t=eb[c + 1]), 1, "next", *p))
        return out
    # cdc arrows start only at a register (the pointer / flag that is synchronized), so an
    # input port does not fan out into every register of the other domain (plan §1)
    if not ctx.graph["nodes"].get(a.key, {}).get("is_state"):
        return out
    best: dict[int, tuple] = {}  # dst cycle -> latest source change explaining it
    for c in sorted(ch[aid]):
        hits = [(ra + rb, -i, cdc_cycle(ea, eb, c, ra, rb), nodes_, vias)
                for i, (nodes_, vias, ra, rb) in enumerate(_cdc_paths(ctx, adj, a, b, c))]
        hits = [h for h in hits if h[2] in ch[bid]]
        if hits:
            regs, _, d, nodes_, vias = max(hits, key=lambda h: (h[0], h[1]))
            best[d] = (ts.End(lane=aid, cycle=c, t=ea[c]), ts.End(lane=bid, cycle=d, t=eb[d]),
                       regs, "cdc", nodes_, vias)
    if not best:
        return []
    # one cdc arrow per lane pair: the earliest crossing; later repeats are counted, not drawn
    first, *rest = sorted(best)
    alog.cdc_dropped += [f"{a.signal}->{b.signal}@{d}" for d in rest]
    return [best[first]]


def cdc_cycle(ea: list[int], eb: list[int], c: int, ra: int, rb: int) -> int:
    """Destination cycle of a cdc change (sampled semantics: a register updated at edge k shows
    at sample k+1). The source changes at A cycle c; its last domain-A register updates at
    ea[c-1+ra]; the first domain-B register at the first B edge k0 strictly after that; the
    j-th domain-B register (and comb logic after it) shows at B cycle k0+j."""
    i = min(max(c - 1 + ra, 0), len(ea) - 1)
    return next((k for k, t in enumerate(eb) if t > ea[i]), len(eb)) + rb


def _cdc_paths(ctx: Ctx, adj, a: LaneSpec, b: LaneSpec, c: int) -> list[tuple]:
    """All register-pair paths lane a (domain A) -> lane b (domain B), BFS order: the path (a
    included) holds >= 1 domain-A register followed by >= 1 domain-B register (b included),
    <= MAX_CDC_REGS registers after a; registers of unknown/other domains are not crossed.
    Every VCD-visible hop is witnessed at its exact cycle (A part at c+rA, B part at
    cdc_cycle). One path per (rA, rB). -> [(nodes, vias, rA, rB)]."""
    ck = ("cdc", a.key, b.key, c)
    if ck in ctx._cache:
        return ctx._cache[ck]
    nodes = ctx.graph["nodes"]
    a_reg = bool(nodes.get(a.key, {}).get("is_state")) and _domain_of_key(ctx, a.key) == a.dom
    ea, eb = ctx.clocks[a.dom].edges, ctx.clocks[b.dom].edges
    start = (a.key, 0, 0)
    prev: dict = {start: None}
    q, hits = deque([start]), []
    while q:
        cur = q.popleft()
        for nxt, via in adj.get(cur[0], []):
            st = _cdc_step(ctx, nodes, cur, nxt, a.dom, b.dom)
            if st is None or st in prev or nxt == a.key:
                continue
            if nxt == b.key:
                if st[2] >= 1 and (st[1] >= 1 or a_reg):
                    prev[st] = (cur, via)
                    hits.append(st)
                continue
            ok = (_witness(ctx, nxt, a.dom, c + st[1]) if st[2] == 0 else
                  _witness(ctx, nxt, b.dom, cdc_cycle(ea, eb, c, st[1], st[2])))
            if ok:
                prev[st] = (cur, via)
                q.append(st)
    res = [(*_unwind(prev, h), h[1], h[2]) for h in hits]
    ctx._cache[ck] = res
    return res


def _cdc_step(ctx: Ctx, nodes: dict, cur: tuple, nxt: str, da: str, db: str):
    _, ra, rb = cur
    if not nodes.get(nxt, {}).get("is_state"):
        return nxt, ra, rb
    dom = _domain_of_key(ctx, nxt)
    if dom == da and rb == 0:
        ra += 1
    elif dom == db:
        rb += 1
    else:
        return None
    return (nxt, ra, rb) if ra + rb <= MAX_CDC_REGS else None


def node_hier(ctx: Ctx, key: str) -> str | None:
    """graph node key -> VCD name (top instance path replaced by the DUT path)."""
    if key.startswith(ctx.inst + "."):
        return ctx.dut + key[len(ctx.inst):]
    return None


def changed(ctx: Ctx, name: str, dom: str, cycle: int) -> bool:
    e = ctx.clocks[dom].edges
    if cycle <= 0 or cycle >= len(e):
        return False
    return ctx.vcd.at(name, e[cycle]) != ctx.vcd.at(name, e[cycle - 1])


def _witness(ctx: Ctx, key: str, dom: str, cycle: int) -> bool:
    """True when the node is not visible in the VCD or changes at `cycle`."""
    name = node_hier(ctx, key)
    if name is None or not ctx.vcd.has(name):
        return True
    return changed(ctx, name, dom, cycle)


def _path(ctx: Ctx, adj, src: str, dst: str, regs: int, dom: str, c: int,
          avoid: frozenset = frozenset()):
    """Path whose every VCD-visible intermediate node also changes (witness): at cycle c
    before the register, at c+1 after it (same domain); for cdc only the r=0 part is checked,
    since the later cycles are in another domain. Nodes in `avoid` are not crossed."""
    ck = ("path", src, dst, regs, dom, c, avoid)
    if ck not in ctx._cache:
        def ok(node: str, r: int) -> bool:
            if node in avoid:
                return False
            if regs > 1 and r > 0:  # cdc: later hops are in the destination domain
                return True
            return _witness(ctx, node, dom, c + r)

        ctx._cache[ck] = None if dst in avoid else find_path(ctx.graph, adj, src, dst, regs, ok)
    return ctx._cache[ck]


def _taken(f: FsmInfo, a: str, b: str) -> list[str] | None:
    """Guards of the transition(s) state a -> state b (sampled values); None when unknown."""
    sa, sb = f.enum.get(a), f.enum.get(b)
    if sa is None or sb is None:
        return None
    conds = [c for s, d, c in f.trans if d == sb and s in (sa, "*")]
    return conds or None


def _idents(conds: list[str], f: FsmInfo) -> list[str]:
    names = {n for c in conds for n in _IDENT.findall(c)}
    return sorted(names - set(f.enum.values()))


def _next_path(ctx: Ctx, adj, a: LaneSpec, b: LaneSpec, c: int, alog: ArrowLog):
    """One-register path a@c -> b@c+1. Paths through an FSM register whose taken transition is
    known must pass a signal its guard reads (preferred); other FSM crossings are blocked."""
    dom, blocked = a.dom, set()
    for fk in sorted(ctx.fsms):
        f = ctx.fsms[fk]
        if fk == a.key or f.dom != dom or not ctx.vcd.has(ctx.hier(f.signal)):
            continue
        vals = ctx.samples(f.signal, dom)
        if c + 1 >= len(vals) or vals[c] == vals[c + 1]:
            continue  # a path through it cannot be witnessed anyway
        conds = _taken(f, vals[c], vals[c + 1])
        if conds is None:
            continue  # unknown transition: generic search may cross it (recorded below)
        blocked.add(fk)
        p = _fsm_path(ctx, adj, a, b, c, f, conds)
        if p is not None:
            return p
    p = _path(ctx, adj, a.key, b.key, 1, dom, c, frozenset(blocked))
    pair = f"{a.signal}@{c} -> {b.signal}@{c + 1}"
    if p is None and blocked and _path(ctx, adj, a.key, b.key, 1, dom, c) is not None:
        fk = sorted(blocked)[0]
        f = ctx.fsms[fk]
        vals = ctx.samples(f.signal, dom)
        alog.rejected.append(f"{pair} ({f.signal} {f.enum[vals[c]]}->{f.enum[vals[c + 1]]}: "
                             f"{' | '.join(_taken(f, vals[c], vals[c + 1]))!r})")
    if p is not None:
        alog.unverified += [(pair, k) for k in p[0][1:] if k in ctx.fsms]
    return p


def _fsm_path(ctx: Ctx, adj, a: LaneSpec, b: LaneSpec, c: int, f: FsmInfo, conds: list[str]):
    """a ->(comb) guard signal k ->(comb) next-state -> f.key ->(comb) b, witnessed."""
    dom = a.dom
    for k in _idents(conds, f):
        kk = ctx.node_key(k)
        if kk is None:
            continue
        if kk == a.key:
            p1 = ([a.key], [])
        elif not _witness(ctx, kk, dom, c):
            continue
        else:
            p1 = _path(ctx, adj, a.key, kk, 0, dom, c)
        p2 = _path(ctx, adj, kk, f.key, 1, dom, c) if p1 is not None else None
        if p2 is None:
            continue
        p3 = ([f.key], []) if f.key == b.key else _path(ctx, adj, f.key, b.key, 0, dom, c + 1)
        if p3 is None:
            continue
        nodes = [*p1[0], *p2[0][1:], *p3[0][1:]]
        if len(set(nodes)) == len(nodes):
            return nodes, [*p1[1], *p2[1], *p3[1]]
    return None


def _arrow_notes(ctx: Ctx, arrows: list, alog: ArrowLog) -> list:
    out = []
    if alog.rejected:
        ex = "; ".join(alog.rejected[:4])
        out.append(ts.Simplification(
            what=f"{len(alog.rejected)} next-cycle arrow candidate(s) not drawn",
            reason="graph path and VCD witness exist, but the path crosses an FSM state "
                   f"register whose taken transition's guard does not read the source: {ex}"))
    if alog.unverified:
        ex = "; ".join(f"{p} via {k.split('.')[-1]}" for p, k in alog.unverified[:4])
        out.append(ts.Simplification(
            what=f"{len(alog.unverified)} arrow(s) cross an FSM register with an unknown "
                 "transition", reason=f"fsm_ext has no guard for the taken transition; kept on "
                                      f"graph path + VCD witness only: {ex}"))
    if alog.cdc_dropped:
        out.append(ts.Simplification(
            what=f"{len(alog.cdc_dropped)} repeated clock-domain-crossing arrow(s) not drawn",
            reason="only the first crossing per lane pair is drawn; the later ones follow the "
                   f"same register path: {'; '.join(alog.cdc_dropped[:4])}"))
    fsm_keys = set(ctx.fsms)
    structural = [a.id for a in arrows
                  if a.kind == "next" and not fsm_keys & set(a.path[1:])]
    if structural:
        out.append(ts.Simplification(
            what=f"arrows {', '.join(structural)} are structural",
            reason="register path + VCD witness only: the write condition of a non-FSM register "
                   "is not evaluated, so a source masked by other logic or a constant parameter "
                   "is not detected"))
    return out


def _split_arrows(arrows: list) -> list[list]:
    """Partition arrows so that no part has more than MAX_ARROWS_PER_CYCLE arrows touching
    (starting or ending at) one time point."""
    parts: list[list] = []
    counts: list[dict[int, int]] = []
    for a in arrows:
        tt = {a.src.t, a.dst.t}
        i = next((k for k, cnt in enumerate(counts)
                  if all(cnt.get(t, 0) < MAX_ARROWS_PER_CYCLE for t in tt)), None)
        if i is None:
            parts.append([])
            counts.append({})
            i = len(parts) - 1
        parts[i].append(a)
        for t in tt:
            counts[i][t] = counts[i].get(t, 0) + 1
    return parts or [[]]


# ---- diagram assembly ---------------------------------------------------------------------
def _stimulus(sim: dict):
    cmd = [shlex.join(c) if isinstance(c, list) else str(c) for c in sim.get("cmd", [])]
    return ts.Stimulus(kind=sim.get("kind", "tb"), tb_path=str(sim.get("tb_path", "")),
                       seed=sim.get("seed"), simulator=str(sim.get("simulator", "")),
                       version=sim.get("version"), cmd=cmd, warnings=list(sim.get("warnings", [])),
                       vcd_sha256=sim.get("vcd_sha256"), timescale=sim.get("timescale"))


def _make(ctx: Ctx, meta: dict, wins: list, lanes: list[LaneSpec], simp: list) -> list:
    """One diagram (plus arrow-split parts) per contiguous span of the scenario's windows."""
    spans = _spans(ctx, lanes, wins)
    base = f"{ctx.design}.{meta['interface']}.{meta['scenario']}"
    ids = [base if j == 1 else f"{base}.w{j}" for j in range(1, len(spans) + 1)]
    out = []
    for j, ((t0, t1, why), ssimp) in enumerate(spans):
        extra = []
        if len(spans) > 1:
            others = ", ".join(f"{i} [{w[0][0]},{w[0][1]}]" for i, w in zip(ids, spans,
                                                                         strict=True))
            extra.append(ts.Simplification(
                what=f"scenario {meta['scenario']} split into {len(spans)} diagrams "
                     f"(this is {j + 1} of {len(spans)})",
                reason=f"drawn lanes change between its windows, which a gap may not hide: "
                       f"{others}"))
        out += _diagram(ctx, meta, ids[j], (t0, t1, why), lanes, [*simp, *ssimp, *extra])
    return out


def _diagram(ctx: Ctx, meta: dict, did: str, win: tuple, lanes: list[LaneSpec],
             simp: list) -> list:
    gaps = _idle_gaps(ctx, lanes, win[0], win[1])
    doms = sorted({ln.dom for ln in lanes}, key=lambda d: (ctx.clocks[d].period, d))
    drawn = {d: _drawn(ctx, d, win, gaps) for d in doms}
    lane_ids: list[tuple[str, LaneSpec]] = []
    domains = []
    simp = list(simp)
    for d in doms:
        dl = []
        for ln in [x for x in lanes if x.dom == d]:
            lid = f"l.{len(lane_ids) + 1}"
            lane_ids.append((lid, ln))
            dl.append(_lane(ctx, lid, ln, drawn[d], simp))
        c = ctx.clocks[d]
        domains.append(ts.Domain(id=d, clock=c.port, period=c.period, phase=c.phase, lanes=dl))
    tgaps, gsimp = _gaps(ctx, doms, gaps)
    arrows, alog = _arrows(ctx, lane_ids, drawn)
    simp += [*gsimp, *_arrow_notes(ctx, arrows, alog)]
    parts = _split_arrows(arrows)
    if len(parts) > 1:
        simp.append(ts.Simplification(
            what=f"arrows split over {len(parts)} diagrams",
            reason=f"a time point has more than {MAX_ARROWS_PER_CYCLE} arrows starting or "
                   "ending there; none dropped"))
    out = []
    for i, part in enumerate(parts, 1):
        out.append(ts.TimingDiagram(
            id=did if i == 1 else f"{did}.p{i}", design=ctx.design, module=ctx.top,
            interface=meta["interface"], protocol=meta["protocol"], scenario=meta["scenario"],
            stimulus=_stimulus(ctx.sim),
            domains=domains if i == 1 else [dm.model_copy(deep=True) for dm in domains],
            windows=[ts.Window(t0=win[0], t1=win[1], reason=win[2])], gaps=tgaps,
            arrows=part, simplifications=simp))
    return out


def _lane(ctx: Ctx, lid: str, ln: LaneSpec, drawn: list[int], simp: list):
    e = ctx.clocks[ln.dom].edges
    vals = ctx.samples(ln.signal, ln.dom)
    if ln.width > 1:
        name = ctx.hier(ln.signal)
        mixed = [e[c] for c in drawn
                 if vals[c] == "x" and set(ctx.vcd.raw_at(name, e[c])) - {"x", "z"}]
        if mixed:
            simp.append(ts.Simplification(
                what=f"lane {ln.signal}: {len(mixed)} partly-unknown bus value(s) shown as x",
                reason=f"bus with some x/z bits has no hex value (first at t={mixed[0]})",
                lines=_lines(ctx, ln)))
    return ts.Lane(id=lid, signal=ln.signal, width=ln.width, role=ln.role,
                   interface=ln.interface, enum=ln.enum,
                   values=[ts.Sample(cycle=c, t=e[c], v=vals[c]) for c in drawn])


def _gaps(ctx: Ctx, doms: list[str], gaps: list):
    out, simp = [], []
    for a, b in gaps:
        cyc = {d: _count(ctx.clocks[d].edges, a, b) for d in doms}
        out.append(ts.Gap(after_t=a, until_t=b, cycles=cyc))
        counts = ", ".join(f"{n} {d}" for d, n in cyc.items())
        simp.append(ts.Simplification(what=f"gap {a}..{b} hides {counts} cycles",
                                      reason="no drawn lane changes in this run"))
    return out, simp


def _l1_dropped(ctx: Ctx, signals: dict) -> list:
    return [ts.Simplification(what=f"L1 selection dropped {d.get('signal')}",
                              reason=str(d.get("reason")),
                              lines=[ts.SrcLine(file=ctx.file_of(ctx.node_key(d["signal"])),
                                                line=int(d["line"]))] if d.get("line") else [])
            for d in signals.get("dropped", []) if d.get("signal")]


def _file_note(ctx: Ctx) -> list:
    if any(n.get("file") for n in ctx.graph["nodes"].values()):
        return []
    if not ctx.files:
        return [ts.Simplification(what="source file unknown",
                                  reason="graph nodes carry no file and no RTL file was given; "
                                         "SrcLine.file=<unknown>")]
    return [ts.Simplification(what="SrcLine.file resolved by module declaration",
                              reason="graph nodes carry no file; files from build(files=), "
                                     "fsm_ext extra.file or sim.json cmd: "
                                     + ", ".join(Path(f).name for f in ctx.files))]


def build_with_log(design: str, signals: dict, graph: dict, sim: dict, vcd, *,
                   fsm_ext: list[dict] | None = None, files: list[str] | None = None):
    """Like build(); also returns design-level notes (skipped interfaces/scenarios, issues)."""
    files = list(files) if files is not None else _rtl_files(graph, sim, fsm_ext)
    try:
        ctx = _context(design, signals, graph, sim, vcd, files)
    except ValueError as ex:
        return [], [{"what": "timing skipped", "reason": str(ex)}]
    fsm = _fsm_lanes(ctx, signals, fsm_ext)
    base = [*_l1_dropped(ctx, signals), *_file_note(ctx)]
    out = []
    for iface in sorted(signals.get("interfaces", []), key=lambda i: i["id"]):
        if iface.get("protocol") == "SIMPLE" or iface.get("demoted_reason"):
            ctx.log.append({"what": f"interface {iface['name']} skipped",
                            "reason": iface.get("demoted_reason") or "SIMPLE"})
            continue
        use, why = _usable(ctx, iface)
        if use is None:
            ctx.log.append({"what": f"interface {iface['name']} skipped", "reason": why})
            continue
        lanes, simp = _cap_lanes(ctx, [*_member_lanes(ctx, iface), *fsm,
                                       *_internal_lanes(ctx, signals, iface["id"])])
        scen = _scenarios(ctx, use)
        if not scen:
            ctx.log.append({"what": f"interface {iface['name']}", "reason": "no event in VCD"})
        for name, wins in scen:
            meta = {"interface": iface["name"], "protocol": iface["protocol"], "scenario": name}
            out += _make(ctx, meta, wins, lanes, [*base, *simp])
    for f in fsm:
        out += _fsm_diagram(ctx, signals, f, fsm, base)
    good = []
    for d in out:
        issues = ts.validate(d)
        if issues:
            ctx.log.append({"what": f"diagram {d.id} rejected", "reason": "; ".join(issues)})
        else:
            good.append(d)
    return good, ctx.log


def _fsm_diagram(ctx: Ctx, signals: dict, f: LaneSpec, fsm: list[LaneSpec], base: list):
    if not ctx.vcd.has(ctx.hier(f.signal)) or f.dom not in ctx.clocks:
        ctx.log.append({"what": f"fsm {f.signal}", "reason": "state register not in the VCD"})
        return []
    wins = _fsm_scenario(ctx, f)
    if not wins:
        ctx.log.append({"what": f"fsm {f.signal}",
                        "reason": "no state transition after reset release in the VCD"})
        return []
    ifs = [i for i in sorted(signals.get("interfaces", []), key=lambda i: i["id"])
           if i.get("protocol") != "SIMPLE" and not i.get("demoted_reason")]
    hs = [ln for i in ifs for ln in _member_lanes(ctx, i) if ln.prio == 0]
    rst = [LaneSpec(r["port"], 1, "reset", (r.get("domains") or [f.dom])[0], r.get("line"), 4,
                    key=ctx.node_key(r["port"])) for r in signals.get("resets", [])]
    near = [x for x in _internal_lanes(ctx, signals, None) if x.signal != f.signal]
    others = [x for x in fsm if x is not f]
    lanes, simp = _cap_lanes(ctx, [f, *hs, *others, *near[:MAX_INTERNAL], *rst])
    for x in near[MAX_INTERNAL:]:
        simp.append(_drop(ctx, x, f"more than {MAX_INTERNAL} internal lanes"))
    meta = {"interface": f.signal, "protocol": "FSM", "scenario": "fsm"}
    return _make(ctx, meta, wins, lanes, [*base, *simp])


def build(design: str, signals: dict, graph: dict, sim: dict, vcd, *,
          fsm_ext: list[dict] | None = None, files: list[str] | None = None) -> list:
    """signals.json + graph.json + sim.json + parsed VCD -> list[TimingDiagram] (all pass
    timing_spec.validate). `files`: RTL files for SrcLine.file when graph nodes carry none
    (default: graph["files"], fsm_ext extra.file, then the RTL arguments of sim.json cmd;
    matched to nodes by `module` declarations)."""
    return build_with_log(design, signals, graph, sim, vcd, fsm_ext=fsm_ext, files=files)[0]


# ---- CLI ----------------------------------------------------------------------------------
def _vcd_path(d: Path, sim: dict) -> Path:
    p = Path(sim.get("vcd") or "")
    for cand in (p, ROOT / p, d / "wave.vcd"):
        if str(cand) and cand.is_file():
            return cand
    raise FileNotFoundError(f"no VCD for {d}")


def summary(dg) -> str:
    rows = [f"{dg.id}  windows={[(w.t0, w.t1) for w in dg.windows]}"]
    for dm in dg.domains:
        n = len(dm.lanes[0].values) if dm.lanes else 0
        rows.append(f"  {dm.id} period={dm.period} drawn={n}")
        for ln in dm.lanes:
            vals = " ".join(ln.enum.get(s.v, s.v) if ln.enum else s.v for s in ln.values)
            rows.append(f"    {ln.id:5s} {ln.signal:12s} {ln.role:6s} {vals}")
    for g in dg.gaps:
        rows.append(f"  gap {g.after_t}..{g.until_t} {g.cycles}")
    for a in dg.arrows:
        rows.append(f"  {a.id} {a.kind:4s} {a.src.lane}@{a.src.cycle} -> {a.dst.lane}@"
                    f"{a.dst.cycle} path={'>'.join(k.split('.')[-1] for k in a.path)} "
                    f"lines={[s.line for s in a.via_lines]}")
    return "\n".join(rows)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--fsm-ext", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    sig = json.loads((a.dir / "signals.json").read_text())
    graph = json.loads((a.dir / "graph.json").read_text())
    sim = json.loads((a.dir / "sim.json").read_text())
    fx = json.loads(a.fsm_ext.read_text()) if a.fsm_ext else None
    v = vcdmod.parse(_vcd_path(a.dir, sim))
    ds, log = build_with_log(sig.get("design") or graph["design"], sig, graph, sim, v, fsm_ext=fx)
    for d in ds:
        print(summary(d))
        if a.out:
            a.out.mkdir(parents=True, exist_ok=True)
            (a.out / f"{d.id}.json").write_text(d.model_dump_json(indent=1))
    for row in log:
        print("note:", row["what"], "-", row["reason"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
