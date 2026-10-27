"""x4 tbgen: deterministic SystemVerilog testbench generated from signals.json (plan §3 Stage 2).

    uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/tbgen.py \
        SIGNALS_JSON ENTRY_JSON OUT_DIR [--cycles 400] [--seed 1]

ENTRY_JSON is one design entry (FORMATS.md "Design entry") or a manifest plus `--name`.
Writes OUT_DIR/tb_gen.sv and prints the returned plan as JSON.

The bench is accepted by `iverilog -g2012` and `verilator --binary --timing`:
- `timescale 1ns/1ps`, module `tb`, DUT instance `dut` with a named connection for every port;
- one clock per domain, periods 10, 14, 18 (then 22, 26, ...), first posedge at period/2. All
  half-periods are odd, so a posedge (odd multiple of a half-period) never coincides with a
  negedge (even multiple) of any domain: TB flags written at posedges are never read at the
  same timestamp, which keeps the run race-free and deterministic;
- every DUT input is a reg written with `<=` on the negedge of its domain's clock;
- pseudo-random choices come from one xorshift32 state per driver, seeded from `seed` and the
  driver index (no $urandom, no wall clock), so the bench is identical across simulators.
Every assumption the generator makes (port without a role, missing width, guessed baud rate,
...) is returned in `notes` with a reason; nothing is dropped silently.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PERIODS = (10, 14, 18)
TB_TOP = "tb"
DUT = "dut"
WIDE = 256  # widest random value a driver produces; wider ports are zero-extended (noted)
_BAUD_INPUT = re.compile(r"(prescale|baud|clk_?div|clks_?per_?bit|divisor)", re.I)
_BAUD_PARAM = re.compile(r"^(CLK_?DIV|CLKS_?PER_?BIT|BAUD_?DIV|DIVISOR|PRESCALE|DIV)$", re.I)
_CLOCK_NAME = re.compile(r"^(i_)?(clk|clock|aclk|[a-z0-9]*_clk|clk_[a-z0-9]*)(_i)?$", re.I)
_RESET_NAME = re.compile(r"^(i_)?([a-z0-9]*_)?(rst|reset|areset|aresetn|rstn)(_?n|_ni|_i)?$",
                         re.I)
_STROBES = ("valid", "req", "enable", "wr", "rd", "we")


# ---------------------------------------------------------------- design discovery (pyslang)


def resolve(p: str | Path) -> Path:
    q = Path(p)
    return q if q.is_absolute() else ROOT / q


def _as_int(text: str) -> int | None:
    s = text.strip().replace("_", "")
    m = re.fullmatch(r"(?:\d+)?'s?([bodhBODH])([0-9a-fA-F]+)", s)
    if m:
        base = {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(1).lower()]
        try:
            return int(m.group(2), base)
        except ValueError:
            return None
    try:
        return int(s)
    except ValueError:
        return None


def elaborate_top(entry: dict, notes: list[dict] | None = None
                  ) -> tuple[list[dict], dict[str, int | None]]:
    """Ports [{name, dir: in|out|inout, width, line, unpacked?}] and parameter defaults of the
    top module, elaborated by slang with default parameters. `entry["ports"]` (same shape)
    skips slang. Unpacked-array ports carry `unpacked: [[left, right], ...]` and the element
    width in `width`. Slang errors (e.g. a syntax error elsewhere) are appended to `notes`."""
    if entry.get("ports"):
        return [dict(p) for p in entry["ports"]], dict(entry.get("params_default") or {})
    import pyslang  # local: tbgen also works from a 'ports' list without pyslang
    from pyslang import driver

    args = ["slang", *[shlex.quote(str(resolve(f))) for f in entry["files"]]]
    for d in entry.get("include_dirs") or []:
        args += ["-I", shlex.quote(str(resolve(d)))]
    for d in entry.get("defines") or []:
        args += ["-D", shlex.quote(d)]
    args += ["--top", entry["top"], "--ignore-unknown-modules", "--timescale=1ns/1ps"]
    drv = driver.Driver()
    drv.addStandardArgs()
    if not (drv.parseCommandLine(" ".join(args), driver.CommandLineOptions())
            and drv.processOptions() and drv.parseAllSources()):
        raise RuntimeError(f"slang could not parse {entry['files']}")
    comp = drv.createCompilation()
    sm = comp.sourceManager
    _slang_errors(comp, sm, pyslang, notes)
    tops = [i for i in comp.getRoot().topInstances if i.name == entry["top"]]
    if not tops:
        raise RuntimeError(f"top module {entry['top']} not found by slang")
    body = tops[0].body
    dirs = {"In": "in", "Out": "out", "InOut": "inout", "Ref": "inout"}
    ports = []
    for p in body.portList:
        d = str(p.direction).split(".")[-1]
        port = {"name": p.name, "dir": dirs.get(d, "inout"), "width": int(p.type.bitWidth),
                "line": sm.getLineNumber(p.location)}
        dims, ty = [], p.type
        while ty.isUnpackedArray and ty.hasFixedRange:
            dims.append([int(ty.fixedRange.left), int(ty.fixedRange.right)])
            ty = ty.elementType
        if dims:
            port.update(width=int(ty.bitWidth), unpacked=dims)
        ports.append(port)
    params = {}
    for prm in body.parameters:
        if getattr(prm, "isLocalParam", False):
            continue
        params[prm.name] = _as_int(str(getattr(prm, "value", "")))
    return ports, params


def _slang_errors(comp, sm, pyslang, notes: list[dict] | None) -> None:
    """Record slang errors as notes: ports are still elaborated, the simulator decides."""
    if notes is None:
        return
    errs = [d for d in comp.getAllDiagnostics() if d.isError()]
    for d in errs[:5]:
        text = pyslang.DiagnosticEngine.reportAll(sm, [d]).strip().splitlines()
        notes.append({"what": "slang error", "reason": (text[0] if text else str(d.code))[:300]
                      + "; ports elaborated anyway, the simulator decides",
                      "line": sm.getLineNumber(d.location)})
    if len(errs) > 5:
        notes.append({"what": "slang error", "reason": f"... {len(errs) - 5} more", "line": None})


# ---------------------------------------------------------------- generator state


class _Tb:
    """Accumulates the bench text. `blocks[d]` holds always-blocks of clock domain index d."""

    def __init__(self, ports: list[dict], seed: int) -> None:
        self.ports = {p["name"]: p for p in ports}
        self.order = [p["name"] for p in ports]
        self.seed = seed
        self.decls: list[str] = []
        self.blocks: list[str] = []
        self.driven: dict[str, str] = {}  # port -> owner ("clock", "reset", "if.x", "other")
        self.init: dict[str, str] = {}  # port -> initial literal
        self.const: dict[str, str] = {}  # port -> constant held for the whole run
        self.notes: list[dict] = []
        self.handshakes: list[dict] = []
        self.params: dict[str, int] = {}
        self.n = 0

    def note(self, what: str, reason: str, line: int | None = None) -> None:
        self.notes.append({"what": what, "reason": reason, "line": line})

    def uid(self) -> int:
        self.n += 1
        return self.n

    def rng(self, k: int) -> str:
        """Declare one xorshift32 state for driver k; return its name."""
        name = f"x4_r{k}"
        val = (0x9E3779B9 * (self.seed * 1009 + k)) & 0xFFFFFFFF or 0x2545F491
        self.decls.append(f"  reg [31:0] {name} = 32'h{val:08x};")
        return name

    def width(self, port: str) -> int:
        return int(self.ports[port]["width"])

    def is_input(self, port: str) -> bool:
        return port in self.ports and self.ports[port]["dir"] == "in"

    def claim(self, port: str, owner: str, init: str = "0") -> bool:
        if port not in self.ports:
            self.note(f"{owner}: member {port}", "not a port of the elaborated top; skipped")
            return False
        if not self.is_input(port):
            return False
        if self.ports[port].get("unpacked"):
            self.note(f"{owner}: member {port}", "unpacked-array port; held 0, not driven by "
                      "this interface")
            return False
        if port in self.driven:
            self.note(f"{owner}: member {port}",
                      f"already driven by {self.driven[port]}; first owner kept")
            return False
        self.driven[port] = owner
        self.init[port] = init
        return True

    def rand_to(self, port: str, r: str, k: int) -> str:
        """Statement assigning a fresh pseudo-random value of the port's width."""
        w = self.width(port)
        if w <= 32:
            return f"{port} <= {r}[{w - 1}:0];" if w > 1 else f"{port} <= {r}[7];"
        if w > WIDE:
            self.note(f"random {port}", f"width {w} > {WIDE}; upper bits held 0")
        tmp = f"x4_t{k}"
        if f"  reg [{WIDE - 1}:0] {tmp};" not in self.decls:
            self.decls.append(f"  reg [{WIDE - 1}:0] {tmp};")
        hi = min(w, WIDE) - 1
        return f"{tmp} = x4_spread({r}); {port} <= {tmp}[{hi}:0];"


def _lit(w: int, v: int) -> str:
    return f"{w}'d{v}"


# ---------------------------------------------------------------- clocks and resets


def _period(i: int) -> int:
    return PERIODS[i] if i < len(PERIODS) else PERIODS[-1] + 4 * (i - len(PERIODS) + 1)


def _edge_free(t: int, periods: list[int]) -> int:
    """First time >= t that is no clock edge of any domain (edges at multiples of P/2)."""
    while any(t % (p // 2) == 0 for p in periods):
        t += 1
    return t


def _clock_plan(signals: dict, tb: _Tb) -> list[dict]:
    clocks: list[dict] = []
    seen: dict[str, dict] = {}
    for c in signals.get("clocks") or []:
        port, dom = c["port"], c.get("domain") or f"d.{c['port']}"
        if port not in tb.ports:
            tb.note(f"clock {port}", "not a port of the elaborated top; skipped", c.get("line"))
            continue
        if dom in seen:
            tb.driven[port] = "clock"
            tb.const[port] = f"__alias__{seen[dom]['port']}"
            tb.note(f"clock {port}", f"same domain {dom} as {seen[dom]['port']}; tied to it")
            continue
        ck = _clock(port, dom, len(clocks), c, tb)
        clocks.append(ck)
        seen[dom] = ck
        tb.driven[port] = "clock"
    if not clocks:
        for name in tb.order:
            if tb.is_input(name) and _CLOCK_NAME.match(name):
                clocks.append(_clock(name, f"d.{name}", len(clocks), {}, tb))
                tb.driven[name] = "clock"
                tb.note(f"clock {name}", "signals.json lists no clock; guessed from the name",
                        tb.ports[name].get("line"))
                break
    if not clocks:
        clocks.append({"port": None, "domain": "d.x4_vclk", "period": 10, "phase": 5,
                       "edge": "posedge"})
        tb.note("clock", "design has no clock; inputs paced by a TB-only clock x4_vclk")
    return clocks


def _clock(port: str, dom: str, i: int, sig: dict, tb: _Tb) -> dict:
    """Clock i of the bench. A negedge domain runs the TB on an internal clock x4_ck_<port>
    and feeds the DUT its inverse, so the DUT's active (falling) edge is the TB's posedge and
    inputs still change half a period away from it. `phase` is the first 0->1 of the DUT port
    (at `period` for a negedge domain, since the port starts at 1)."""
    p = _period(i)
    edge = sig.get("edge") or "posedge"
    ck = {"port": port, "domain": dom, "period": p, "phase": p // 2, "edge": "posedge"}
    if edge == "negedge":
        ck.update(edge="negedge", phase=p, tbclk=f"x4_ck_{port}")
        tb.const[port] = f"__alias__~x4_ck_{port}"
        tb.note(f"clock {port}", "negedge domain: inputs change on the port's rising edge "
                f"(TB clock x4_ck_{port} = ~{port}); first active (falling) edge at {p // 2}",
                sig.get("line"))
    elif edge != "posedge":
        tb.note(f"clock {port}", f"edge {edge!r} not supported; driven as a posedge domain",
                sig.get("line"))
    return ck


def _reset_plan(signals: dict, tb: _Tb, release_t: int) -> list[dict]:
    resets = []
    listed = {r["port"]: r for r in signals.get("resets") or []}
    for name in tb.order:
        if name in listed or not tb.is_input(name) or name in tb.driven:
            continue
        if _RESET_NAME.match(name) and not any(
                m["port"] == name for i in signals.get("interfaces") or []
                for m in i.get("members") or []):
            low = name.lower().endswith(("n", "_ni"))
            listed[name] = {"port": name, "active_low": low}
            tb.note(f"reset {name}", f"not in signals.json; guessed from the name "
                    f"(active_{'low' if low else 'high'})", tb.ports[name].get("line"))
    for port, r in listed.items():
        if port not in tb.ports:
            tb.note(f"reset {port}", "not a port of the elaborated top; skipped", r.get("line"))
            continue
        low = bool(r.get("active_low"))
        if tb.claim(port, "reset", "1'b0" if low else "1'b1"):
            resets.append({"port": port, "active_low": low, "release_t": release_t})
    return resets


# ---------------------------------------------------------------- per-interface drivers


def _roles(iface: dict, tb: _Tb) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for m in iface.get("members") or []:
        out.setdefault(m.get("role") or "data", []).append(m["port"])
    return out


def _first(roles: dict, *names: str) -> str | None:
    for n in names:
        if roles.get(n):
            return roles[n][0]
    return None


def _member_domain(iface: dict, port: str, doms: dict[str, int], tb: _Tb) -> int:
    for m in iface.get("members") or []:
        if m["port"] == port and m.get("domain") in doms:
            return doms[m["domain"]]
    if iface.get("domain") in doms:
        return doms[iface["domain"]]
    tb.note(f"{iface['id']}: domain of {port}",
            f"unknown domain {iface.get('domain')!r}; driven from the first clock")
    return 0


def _payload(roles: dict, skip: tuple[str, ...]) -> list[tuple[str, str]]:
    return [(p, role) for role, ps in roles.items() if role not in skip for p in ps]


def _drive_payload(tb: _Tb, members: list[tuple[str, str]], owner: str, r: str, k: int,
                   ctr: str) -> list[str]:
    """Statements for the data-like inputs of one beat: the widest data member carries the
    beat counter, addresses cycle over 4 word-aligned values, the rest are pseudo-random."""
    mine = [(p, role) for p, role in members if tb.claim(p, owner)]
    data = [p for p, role in mine if role in ("data", "wdata")]
    main = max(data, key=tb.width, default=None)
    stmts = []
    for p, role in mine:
        if role == "addr":
            stmts.append(f"{p} <= {_addr_expr(tb, p, f'({r} >> 8) % 4')};")
        elif p == main:
            stmts.append(f"{p} <= {ctr};")
        else:
            stmts.append(tb.rand_to(p, r, k))
    return stmts


def _addr_expr(tb: _Tb, port: str, idx: str) -> str:
    stride = 4 if tb.width(port) >= 4 else 1
    return f"({idx}) * {stride}"


def _vr(tb: _Tb, iface: dict, doms: dict, clocks: list[dict]) -> None:
    roles, iid = _roles(iface, tb), iface["id"]
    valid, ready = _first(roles, "valid"), _first(roles, "ready")
    if not valid or not ready:
        tb.note(f"{iid}", f"VALID_READY without {'valid' if not valid else 'ready'}; "
                "members driven as other inputs")
        _plain(tb, iface, doms, clocks)
        return
    d = _member_domain(iface, valid, doms, tb)
    clk = _clk(clocks, d)
    tb.handshakes.append({"interface": iid, "protocol": iface["protocol"], "clock": clk,
                          "domain": clocks[d]["domain"], "fire": [valid, ready]})
    if tb.is_input(valid):
        _vr_producer(tb, iface, roles, valid, ready, clk)
    if tb.is_input(ready):
        _vr_consumer(tb, iid, valid, ready, _clk(clocks, _member_domain(iface, ready, doms, tb)))
    if not tb.is_input(valid) and not tb.is_input(ready):
        tb.note(iid, "valid and ready are both DUT outputs; nothing to drive")


def _vr_producer(tb: _Tb, iface: dict, roles: dict, valid: str, ready: str, clk: str) -> None:
    k = tb.uid()
    iid = iface["id"]
    if not tb.claim(valid, iid):
        return
    r, f, n = tb.rng(k), f"x4_f{k}", f"x4_n{k}"
    tb.decls += [f"  reg {f} = 1'b0;", f"  integer {n} = 1;"]
    beat = _drive_payload(tb, _payload(roles, ("valid", "ready")), iid, r, k, n)
    if iface.get("direction") == "out":
        tb.note(iid, "direction 'out' but valid is a DUT input; TB acts as producer")
    tb.blocks.append(f"""  // {iid} VALID_READY producer: valid p=0.6, held until valid&&ready
  always @(posedge {clk}) {f} <= {valid} && {ready};
  always @(negedge {clk}) begin
    if (!x4_act) begin
      {valid} <= 1'b0;
    end else if (!{valid} || {f}) begin
      {r} = x4_xs({r});
      if ({f}) {n} = {n} + 1;
      {valid} <= ({r} % 100) < 60;
      {_join(beat, 6)}
    end
  end""")


def _vr_consumer(tb: _Tb, iid: str, valid: str, ready: str, clk: str) -> None:
    k = tb.uid()
    if not tb.claim(ready, iid):
        return
    r, s = tb.rng(k), f"x4_s{k}"
    tb.decls.append(f"  integer {s} = 0;")
    trig = valid if valid in tb.ports else "1'b1"
    tb.blocks.append(f"""  // {iid} VALID_READY consumer: ready p=0.7, one 4-cycle stall
  // at the first valid after reset
  always @(negedge {clk}) begin
    if (!x4_act) begin
      {ready} <= 1'b0;
    end else begin
      {r} = x4_xs({r});
      if ({s} == 0 && {trig}) {s} = 1;
      if ({s} >= 1 && {s} <= 4) begin
        {ready} <= 1'b0;
        {s} = {s} + 1;
      end else begin
        {ready} <= ({r} % 100) < 70;
      end
    end
  end""")


def _stream(tb: _Tb, iface: dict, doms: dict, clocks: list[dict]) -> None:
    roles, iid = _roles(iface, tb), iface["id"]
    valid = _first(roles, "valid", "enable", "tick")
    if not valid or not tb.is_input(valid):
        tb.note(iid, "STREAM produced by the DUT (or without valid); nothing to drive")
        _plain(tb, iface, doms, clocks)
        return
    k = tb.uid()
    d = _member_domain(iface, valid, doms, tb)
    clk = _clk(clocks, d)
    if not tb.claim(valid, iid):
        return
    r, n, c = tb.rng(k), f"x4_n{k}", f"x4_c{k}"
    tb.decls += [f"  integer {n} = 1;", f"  integer {c} = 0;"]
    beat = _drive_payload(tb, [m for m in _payload(roles, ()) if m[0] != valid], iid, r, k, n)
    tb.handshakes.append({"interface": iid, "protocol": "STREAM", "clock": clk,
                          "domain": clocks[d]["domain"], "fire": [valid]})
    tb.blocks.append(f"""  // {iid} STREAM producer: bursts of 4 valid cycles every 10 cycles
  always @(negedge {clk}) begin
    if (!x4_act) begin
      {valid} <= 1'b0;
    end else begin
      {r} = x4_xs({r});
      {valid} <= ({c} % 10) < 4;
      if (({c} % 10) < 4) begin
        {_join(beat, 8)}
        {n} = {n} + 1;
      end
      {c} = {c} + 1;
    end
  end""")


def _reqack(tb: _Tb, iface: dict, doms: dict, clocks: list[dict]) -> None:
    roles, iid = _roles(iface, tb), iface["id"]
    req, ack = _first(roles, "req", "valid"), _first(roles, "ack", "ready")
    if not req:
        tb.note(iid, "REQ_ACK without req; members driven as other inputs")
        _plain(tb, iface, doms, clocks)
        return
    d = _member_domain(iface, req, doms, tb)
    clk = _clk(clocks, d)
    if ack:
        tb.handshakes.append({"interface": iid, "protocol": iface["protocol"], "clock": clk,
                              "domain": clocks[d]["domain"], "fire": [req, ack]})
    payload = _payload(roles, ("req", "ack", "valid", "ready"))
    if tb.is_input(req):
        _requester(tb, iid, req, ack, payload, clk)
    elif ack and tb.is_input(ack):
        _responder(tb, iid, req, ack, [p for p, _ in payload], clk, latency=2)
    else:
        tb.note(iid, "req and ack are DUT outputs (or ack missing); nothing to drive")
        _plain(tb, iface, doms, clocks)


def _requester(tb: _Tb, iid: str, req: str, ack: str | None,
               payload: list[tuple[str, str]], clk: str) -> None:
    k = tb.uid()
    if not tb.claim(req, iid):
        return
    r, f, n, c = tb.rng(k), f"x4_f{k}", f"x4_n{k}", f"x4_c{k}"
    tb.decls += [f"  reg {f} = 1'b0;", f"  integer {n} = 1;", f"  integer {c} = 0;"]
    beat = _drive_payload(tb, payload, iid, r, k, n)
    if ack is None:
        tb.note(iid, "REQ_ACK without ack: each request lasts one cycle")
    fire = f"{req} && {ack}" if ack else f"{req}"
    tb.blocks.append(f"""  // {iid} REQ_ACK requester: one request every 8 cycles, held until ack
  always @(posedge {clk}) {f} <= {fire};
  always @(negedge {clk}) begin
    if (!x4_act) begin
      {req} <= 1'b0;
    end else begin
      {r} = x4_xs({r});
      if ({req}) begin
        if ({f}) begin
          {req} <= 1'b0;
          {n} = {n} + 1;
        end
      end else if ({c} % 8 == 0) begin
        {req} <= 1'b1;
        {_join(beat, 8)}
      end
      {c} = {c} + 1;
    end
  end""")


def _responder(tb: _Tb, iid: str, req: str | None, ack: str, payload: list[str], clk: str,
               *, latency: int) -> None:
    k = tb.uid()
    if not tb.claim(ack, iid):
        return
    r, w = tb.rng(k), f"x4_w{k}"
    tb.decls.append(f"  integer {w} = 0;")
    beat = [tb.rand_to(p, r, k) for p in payload if tb.claim(p, iid)]
    if req is None or req not in tb.ports:
        tb.note(iid, f"responder without a request output; {ack} held 1 after reset")
        tb.blocks.append(f"""  // {iid} responder: {ack} held 1 (no request signal)
  always @(negedge {clk}) begin
    {r} = x4_xs({r});
    {ack} <= x4_act;
    {_join(beat, 4)}
  end""")
        return
    tb.blocks.append(f"""  // {iid} responder: {ack} pulses after {req} high for {latency}
  always @(negedge {clk}) begin
    if (!x4_act) begin
      {ack} <= 1'b0;
      {w} = 0;
    end else if ({ack}) begin
      {ack} <= 1'b0;
      {w} = 0;
    end else if ({req}) begin
      {w} = {w} + 1;
      if ({w} >= {latency}) begin
        {r} = x4_xs({r});
        {ack} <= 1'b1;
        {_join(beat, 8)}
      end
    end else begin
      {w} = 0;
    end
  end""")


def _membus(tb: _Tb, iface: dict, doms: dict, clocks: list[dict]) -> None:
    roles, iid = _roles(iface, tb), iface["id"]
    addr = _first(roles, "addr")
    if not addr:
        tb.note(iid, "MEMORY_BUS without addr; members driven as other inputs")
        _plain(tb, iface, doms, clocks)
        return
    d = _member_domain(iface, addr, doms, tb)
    clk = _clk(clocks, d)
    strobe = next((p for n in _STROBES if n not in ("wr", "rd", "we")
                   for p in roles.get(n, [])), None)
    hs = _first(roles, "ready", "ack")
    if strobe and hs:
        tb.handshakes.append({"interface": iid, "protocol": "MEMORY_BUS", "clock": clk,
                              "domain": clocks[d]["domain"], "fire": [strobe, hs]})
    if tb.is_input(addr):
        _mem_master(tb, iid, roles, addr, strobe, hs, clk)
    else:
        payload = [p for role in ("rdata", "data") for p in roles.get(role, [])]
        req = strobe or next((p for n in ("we", "wr", "rd") for p in roles.get(n, [])), None)
        if hs and tb.is_input(hs):
            _responder(tb, iid, req, hs, payload, clk, latency=1)
        else:
            tb.note(iid, "MEMORY_BUS slave without ack/ready input; read data random")
            _plain(tb, iface, doms, clocks)


def _mem_master(tb: _Tb, iid: str, roles: dict, addr: str, strobe: str | None,
                hs: str | None, clk: str) -> None:
    k = tb.uid()
    r, f, n, op = tb.rng(k), f"x4_f{k}", f"x4_n{k}", f"x4_op{k}"
    tb.decls += [f"  reg {f} = 1'b0;", f"  integer {n} = 1;", f"  integer {op} = 0;",
                 f"  reg x4_wr{k} = 1'b0;", f"  integer x4_a{k} = 0;"]
    tb.claim(addr, iid)
    st = []
    if strobe and tb.claim(strobe, iid):
        st.append(f"{strobe} <= (x4_op{k} < 8) || {r}[3];")
    for p in roles.get("we", []) + roles.get("wr", []):
        if tb.claim(p, iid):
            st.append(f"{p} <= x4_wr{k};")
    for p in roles.get("rd", []):
        if tb.claim(p, iid):
            st.append(f"{p} <= !x4_wr{k};")
    st.append(f"{addr} <= {_addr_expr(tb, addr, f'x4_a{k}')};")
    data = [p for role in ("wdata", "data") for p in roles.get(role, []) if tb.claim(p, iid)]
    st += [f"{p} <= {n};" for p in data]
    hold = f"{strobe} && !{f}" if (strobe and hs and tb.driven.get(strobe) == iid) else ""
    if hold:
        tb.blocks.append(f"  always @(posedge {clk}) {f} <= {strobe} && {hs};")
    else:
        tb.note(iid, "MEMORY_BUS master without strobe+handshake pair: one op per cycle")
    tb.blocks.append(f"""  // {iid} MEMORY_BUS master: 4 writes, 4 reads back, then random
  always @(negedge {clk}) begin
    if (!x4_act) begin
      {op} = 0;
    end else if ({hold or "1'b0"}) begin
      // hold the op until accepted
    end else begin
      {r} = x4_xs({r});
      if ({op} < 8) begin
        x4_wr{k} = {op} < 4;
        x4_a{k} = {op} % 4;
      end else begin
        x4_wr{k} = {r}[0];
        x4_a{k} = ({r} >> 1) % 4;
      end
      {_join(st, 6)}
      if (x4_wr{k}) {n} = {n} + 1;
      {op} = {op} + 1;
    end
  end""")


def _fifo(tb: _Tb, iface: dict, doms: dict, clocks: list[dict]) -> None:
    roles, iid = _roles(iface, tb), iface["id"]
    wr, rd = _first(roles, "wr"), _first(roles, "rd")
    if not wr and not rd:
        if roles.get("valid") and roles.get("ready"):
            _vr(tb, iface, doms, clocks)
        else:
            tb.note(iid, "FIFO without wr/rd; members driven as other inputs")
            _plain(tb, iface, doms, clocks)
        return
    full, empty = _first(roles, "full"), _first(roles, "empty")
    k = tb.uid()
    wn, rn = f"x4_wn{k}", f"x4_rn{k}"
    tb.decls += [f"  integer {wn} = 0;", f"  integer {rn} = 0;"]
    for side, sig, flag in (("write", wr, full), ("read", rd, empty)):
        if not sig:
            tb.note(iid, f"FIFO without {side} strobe; that side not driven")
            continue
        if not flag:
            tb.note(iid, f"FIFO {side} side without {'full' if side == 'write' else 'empty'};"
                    " strobes not gated")
        d = _member_domain(iface, sig, doms, tb)
        tb.handshakes.append({"interface": iid, "protocol": "FIFO", "clock": _clk(clocks, d),
                              "domain": clocks[d]["domain"],
                              "fire": [sig, f"!{flag}"] if flag else [sig]})
        if tb.is_input(sig) and tb.claim(sig, iid):
            _fifo_side(tb, iface, roles, k, side, sig, flag, _clk(clocks, d))


def _fifo_side(tb: _Tb, iface: dict, roles: dict, k: int, side: str, sig: str,
               flag: str | None, clk: str) -> None:
    r = tb.rng(k * 10 + (1 if side == "write" else 2))
    wn, rn = f"x4_wn{k}", f"x4_rn{k}"
    ok = f"!{flag}" if flag else "1'b1"
    mine = wn if side == "write" else rn
    st = []
    if side == "write":
        data = [p for role in ("data", "wdata") for p in roles.get(role, [])
                if tb.ports.get(p, {}).get("dir") == "in"]
        st = [f"{p} <= {wn} + 1;" for p in data if tb.claim(p, iface["id"])]
        phase = f"""if ({wn} < 6) {sig} <= {ok};
      else if ({rn} < 6) {sig} <= 1'b0;"""
    else:
        phase = f"""if ({wn} < 6) {sig} <= 1'b0;
      else if ({rn} < 6) {sig} <= {ok};"""
    tb.blocks.append(f"""  // {iface['id']} FIFO {side}: 6 writes, 6 reads, then interleaved
  always @(posedge {clk}) if (x4_act && {sig} && {ok}) {mine} = {mine} + 1;
  always @(negedge {clk}) begin
    if (!x4_act) begin
      {sig} <= 1'b0;
    end else begin
      {r} = x4_xs({r});
      {phase}
      else {sig} <= ({r} % 100) < 50 && {ok};
      {_join(st, 6)}
    end
  end""")


def _serial(tb: _Tb, iface: dict, doms: dict, clocks: list[dict], baud: dict) -> None:
    roles, iid = _roles(iface, tb), iface["id"]
    line = _first(roles, "serial", "data")
    if not line or not tb.is_input(line) or tb.width(line) != 1:
        tb.note(iid, "SERIAL line is a DUT output (or not 1 bit); nothing to drive")
        _plain(tb, iface, doms, clocks)
        return
    d = _member_domain(iface, line, doms, tb)
    clk = _clk(clocks, d)
    if not tb.claim(line, iid, "1'b1"):
        return
    k = tb.uid()
    bits, nb = baud["bit_cycles"], baud["data_bits"]
    tb.decls += [f"  integer x4_sc{k} = 0;", f"  integer x4_sb{k} = 0;",
                 f"  reg [{nb - 1}:0] x4_sd{k} = {_lit(nb, 0x55 & ((1 << nb) - 1))};"]
    tb.handshakes.append({"interface": iid, "protocol": "SERIAL", "clock": clk,
                          "domain": clocks[d]["domain"], "fire": [], "bit_cycles": bits})
    stop = nb + 3
    tb.blocks.append(f"""  // {iid} SERIAL rx: 2 idle bits, start, {nb} data LSB first, stop;
  // {bits} clock cycles per bit ({baud['reason']})
  always @(negedge {clk}) begin
    if (!x4_act) begin
      {line} <= 1'b1;
    end else begin
      if (x4_sb{k} < 2) {line} <= 1'b1;
      else if (x4_sb{k} == 2) {line} <= 1'b0;
      else if (x4_sb{k} < {stop}) {line} <= x4_sd{k}[x4_sb{k} - 3];
      else {line} <= 1'b1;
      x4_sc{k} = x4_sc{k} + 1;
      if (x4_sc{k} == {bits}) begin
        x4_sc{k} = 0;
        x4_sb{k} = x4_sb{k} + 1;
        if (x4_sb{k} > {stop}) begin
          x4_sb{k} = 0;
          x4_sd{k} = x4_sd{k} + {_lit(nb, 0x13 % (1 << nb) or 1)};
        end
      end
    end
  end""")


def _baud(tb: _Tb, signals: dict, params: dict[str, int | None]) -> dict:
    """Bit time for a UART-like rx frame: a prescale-like input set to 1 (verilog-uart counts
    8 clocks per prescale unit), else a divider parameter's default value, else 16."""
    nb = params.get("DATA_WIDTH") or 8
    nb = nb if 5 <= nb <= 16 else 8
    for name in tb.order:
        if tb.is_input(name) and _BAUD_INPUT.search(name) and name not in tb.driven \
                and not tb.ports[name].get("unpacked"):
            tb.claim(name, "baud", _lit(tb.width(name), 1))
            tb.const[name] = _lit(tb.width(name), 1)
            tb.note(f"input {name}", "baud/prescale-like input held at 1 for the SERIAL frames "
                    "(8 clocks per bit assumed, verilog-uart convention)",
                    tb.ports[name].get("line"))
            return {"bit_cycles": 8, "data_bits": nb, "input": name,
                    "reason": f"{name}=1, assuming 8 clocks per prescale unit (verilog-uart)"}
    for pname, v in params.items():
        if _BAUD_PARAM.match(pname) and v:
            if v <= 64:
                return {"bit_cycles": v, "data_bits": nb, "input": None,
                        "reason": f"parameter {pname}={v} clocks per bit"}
            tb.params[pname] = 16
            tb.note(f"parameter {pname}", f"default {v} too slow for the run; overridden to 16")
            return {"bit_cycles": 16, "data_bits": nb, "input": None,
                    "reason": f"parameter {pname} overridden to 16"}
    return {"bit_cycles": 16, "data_bits": nb, "input": None,
            "reason": "no baud input or parameter found; 16 clocks per bit assumed"}


def _plain(tb: _Tb, iface: dict, doms: dict, clocks: list[dict]) -> None:
    for m in iface.get("members") or []:
        p = m["port"]
        if not tb.is_input(p) or p in tb.driven:
            continue
        kind = "data" if (m.get("role") in ("data", "wdata", "addr", "rdata")
                          and tb.width(p) > 1) else "control"
        _other(tb, {"port": p, "domain": m.get("domain") or iface.get("domain"),
                    "kind": kind, "line": m.get("line")}, doms, clocks, owner=iface["id"])


def _other(tb: _Tb, o: dict, doms: dict, clocks: list[dict], owner: str = "other") -> None:
    p = o["port"]
    if p not in tb.ports:
        tb.note(f"other input {p}", "not a port of the elaborated top; skipped", o.get("line"))
        return
    if tb.driven.get(p) == "baud":
        return  # already held at 1 by _baud (noted there)
    if _BAUD_INPUT.search(p) and tb.is_input(p) and p not in tb.driven:
        tb.claim(p, owner, _lit(tb.width(p), 1))
        tb.const[p] = _lit(tb.width(p), 1)
        tb.note(f"input {p}", "baud/prescale-like input held at 1 (fastest legal rate)",
                o.get("line"))
        return
    if not tb.claim(p, owner):
        return
    if o.get("kind") != "data" or tb.width(p) == 1:
        tb.const[p] = _lit(tb.width(p), 0)
        return
    d = doms.get(o.get("domain"), 0)
    k = tb.uid()
    r = tb.rng(k)
    tb.blocks.append(f"""  // {p}: data input, pseudo-random every cycle
  always @(negedge {_clk(clocks, d)}) begin
    {r} = x4_xs({r});
    {tb.rand_to(p, r, k)}
  end""")


def _clk(clocks: list[dict], d: int) -> str:
    """Clock the TB blocks of domain d run on (its posedge is the DUT's active edge)."""
    return clocks[d].get("tbclk") or clocks[d]["port"] or "x4_vclk"


def _join(stmts: list[str], indent: int) -> str:
    return ("\n" + " " * indent).join(stmts) if stmts else "// no payload"


# ---------------------------------------------------------------- assembly


_HELPERS = """  function automatic [31:0] x4_xs(input [31:0] x);
    reg [31:0] y;
    begin
      y = x ^ (x << 13);
      y = y ^ (y >> 17);
      x4_xs = y ^ (y << 5);
    end
  endfunction
  function automatic [255:0] x4_spread(input [31:0] x);
    integer i;
    reg [31:0] y;
    begin
      y = x;
      x4_spread = 256'd0;
      for (i = 0; i < 8; i = i + 1) begin
        y = x4_xs(y);
        x4_spread = {x4_spread[223:0], y};
      end
    end
  endfunction"""


def _port_decls(tb: _Tb) -> list[str]:
    out = []
    for name in tb.order:
        p = tb.ports[name]
        rng = f" [{p['width'] - 1}:0]" if p["width"] > 1 else ""
        if p.get("unpacked"):
            out += _array_decl(name, p, rng)
            continue
        if p["dir"] == "in":
            alias = tb.const.get(name, "")
            if alias.startswith("__alias__"):
                out.append(f"  wire{rng} {name};")
                out.append(f"  assign {name} = {alias[9:]};")
            elif name in tb.const:
                out.append(f"  reg{rng} {name} = {tb.const[name]};")
            else:
                out.append(f"  reg{rng} {name} = {tb.init.get(name, '0')};")
        else:
            out.append(f"  wire{rng} {name};")
    return out


def _array_decl(name: str, p: dict, rng: str) -> list[str]:
    """Unpacked-array port: a matching array; an input is zeroed element by element."""
    dims = "".join(f" [{lo}:{hi}]" for lo, hi in p["unpacked"])
    if p["dir"] != "in":
        return [f"  wire{rng} {name}{dims};"]
    out = [f"  reg{rng} {name}{dims};"]
    idx = [f"x4_i{j}" for j in range(len(p["unpacked"]))]
    loops = [f"for ({i} = {min(lo, hi)}; {i} <= {max(lo, hi)}; {i} = {i} + 1)"
             for i, (lo, hi) in zip(idx, p["unpacked"], strict=True)]
    out.append(f"  initial begin : x4_zero_{name}\n    integer {', '.join(idx)};\n    "
               f"{' '.join(loops)} {name}{''.join(f'[{i}]' for i in idx)} = 0;\n  end")
    return out


def _unowned(tb: _Tb) -> None:
    for name in tb.order:
        p = tb.ports[name]
        if p["dir"] == "in" and p.get("unpacked") and name not in tb.driven:
            tb.driven[name] = "default"
            tb.note(f"input {name}", "unpacked-array input "
                    f"{''.join(f'[{lo}:{hi}]' for lo, hi in p['unpacked'])}; every element "
                    "held 0", p.get("line"))
        elif p["dir"] == "in" and name not in tb.driven:
            tb.driven[name] = "default"
            tb.const[name] = _lit(p["width"], 0)
            tb.note(f"input {name}", "in no interface, clock, reset or other_inputs; held 0",
                    p.get("line"))
        elif p["dir"] == "inout":
            tb.note(f"inout {name}", "left undriven (wire)", p.get("line"))


def _dut(tb: _Tb, top: str) -> list[str]:
    conns = [f"    .{n}({n})" for n in tb.order]
    if tb.params:
        ps = ", ".join(f".{k}({v})" for k, v in sorted(tb.params.items()))
        head = f"  {top} #({ps}) {DUT} ("
    else:
        head = f"  {top} {DUT} ("
    return [head, ",\n".join(conns), "  );"]


def _render(tb: _Tb, signals: dict, top: str, clocks: list[dict], resets: list[dict],
            release_t: int, end_t: int, seed: int, cycles: int) -> str:
    lines = [
        f"// x4 tbgen: generated testbench for {signals.get('design', top)} (top {top}).",
        f"// seed={seed} cycles={cycles} end_t={end_t} release_t={release_t}. Do not edit.",
        "// verilator lint_off WIDTH",
        "// verilator lint_off UNUSED",
        "// verilator lint_off BLKSEQ",
        "`timescale 1ns/1ps",
        f"module {TB_TOP};",
        _HELPERS,
        "  reg x4_act = 1'b0;  // stimulus enabled once reset is released",
    ]
    tbclks = [c.get("tbclk") or "x4_vclk" for c in clocks if c.get("tbclk") or not c["port"]]
    lines += [f"  reg {name} = 1'b0;" for name in tbclks]  # before a port `assign` uses it
    lines += _port_decls(tb)
    for c in clocks:
        name = c.get("tbclk") or c["port"] or "x4_vclk"
        lines.append(f"  always #{c['period'] // 2} {name} = ~{name};  "
                     f"// {c['domain']} period {c['period']}, first posedge {c['phase']}")
    lines += tb.decls
    lines += _dut(tb, top)
    lines += tb.blocks
    rel = [f"    {r['port']} = 1'b{1 if r['active_low'] else 0};" for r in resets]
    lines += ["  initial begin", f"    #{release_t};", *rel, "    x4_act = 1'b1;", "  end",
              "  initial begin", '    $dumpfile("wave.vcd");', f"    $dumpvars(0, {TB_TOP});",
              f"    #{end_t};", "    $finish;", "  end", "endmodule",
              "// verilator lint_on BLKSEQ", "// verilator lint_on UNUSED",
              "// verilator lint_on WIDTH", ""]
    return "\n".join(lines)


_DRIVERS = {"VALID_READY": _vr, "STREAM": _stream, "REQ_ACK": _reqack, "MEMORY_BUS": _membus,
            "FIFO": _fifo}


def generate(signals: dict, entry: dict, out_dir: Path, *, cycles: int = 400,
             seed: int = 1) -> dict:
    """Write out_dir/tb_gen.sv. Returns {tb_path, tb_top, dut_path, clocks[{port, domain,
    period, phase}], resets[{port, active_low, release_t}], end_t, seed, cycles, params,
    handshakes[{interface, protocol, clock, domain, fire[ports]}], notes[{what, reason,
    line}], time_unit}. Times are in TB units (time_unit "1ns"); sim.json rescales them to
    the VCD timescale."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slang_notes: list[dict] = []
    ports, params = elaborate_top(entry, slang_notes)
    tb = _Tb(ports, seed)
    tb.notes += slang_notes
    _width_check(tb, signals)
    clocks = _clock_plan(signals, tb)
    periods = [c["period"] for c in clocks]
    release_t = _edge_free(3 * max(periods), periods)
    resets = _reset_plan(signals, tb, release_t)
    doms = {c["domain"]: i for i, c in enumerate(clocks)}
    serial = any(i.get("protocol") == "SERIAL" for i in signals.get("interfaces") or [])
    baud = _baud(tb, signals, params) if serial else None
    for iface in signals.get("interfaces") or []:
        proto = iface.get("protocol")
        if proto == "SERIAL":
            _serial(tb, iface, doms, clocks, baud)
        elif proto in _DRIVERS:
            _DRIVERS[proto](tb, iface, doms, clocks)
        else:
            tb.note(iface["id"], f"protocol {proto}: members driven as other inputs")
            _plain(tb, iface, doms, clocks)
    for o in signals.get("other_inputs") or []:
        _other(tb, o, doms, clocks)
    _unowned(tb)
    end_t = cycles * min(periods)
    text = _render(tb, signals, entry["top"], clocks, resets, release_t, end_t, seed, cycles)
    path = out_dir / "tb_gen.sv"
    path.write_text(text, encoding="utf-8")
    clocks = [{k: v for k, v in c.items() if k != "tbclk"} for c in clocks]
    return {"tb_path": str(path), "tb_top": TB_TOP, "dut_path": f"{TB_TOP}.{DUT}",
            "time_unit": "1ns", "clocks": clocks, "resets": resets, "end_t": end_t, "seed": seed,
            "cycles": cycles, "params": dict(tb.params), "handshakes": tb.handshakes,
            "notes": tb.notes}


def _width_check(tb: _Tb, signals: dict) -> None:
    for i in signals.get("interfaces") or []:
        for m in i.get("members") or []:
            p = tb.ports.get(m["port"])
            if p and m.get("width") not in (None, p["width"]):
                tb.note(f"width {m['port']}", f"signals.json says {m['width']}, elaborated "
                        f"top says {p['width']}; elaborated width used", m.get("line"))


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("signals")
    ap.add_argument("entry")
    ap.add_argument("out_dir")
    ap.add_argument("--name", help="entry name when ENTRY_JSON is a manifest list")
    ap.add_argument("--cycles", type=int, default=400)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    sig = json.loads(Path(a.signals).read_text())
    ent = json.loads(Path(a.entry).read_text())
    if isinstance(ent, list):
        ent = next(e for e in ent if e["name"] == a.name)
    res = generate(sig, ent, Path(a.out_dir), cycles=a.cycles, seed=a.seed)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
