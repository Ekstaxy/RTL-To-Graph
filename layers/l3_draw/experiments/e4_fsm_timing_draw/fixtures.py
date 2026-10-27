"""Hand-written FsmGraph v0.1 / TimingDiagram v0.1 dicts for the e4 self-test (not RTL-derived;
names and values are made up to exercise every drawing rule). Imported by selftest.py only.
"""

from __future__ import annotations


def _st(name, value, *, reset=False, reached=True, unnamed=False):
    return {"id": f"s.{name}", "name": name, "value": value, "reset": reset,
            "reached": reached, "unnamed": unnamed}


def _tr(n, src, dst, guard, kind="expr", seen=("both",), line=None):
    lines = [{"file": "fixture.sv", "line": line}] if line else []
    return {"id": f"t.{n}", "src": f"s.{src}", "dst": f"s.{dst}", "guard": guard,
            "guard_kind": kind, "lines": lines, "seen_by": list(seen)}


def _fsm(design, module, reg, width, enc, states, trs, **checks):
    return {"schema_version": "fsm-0.1", "design": design, "module": module,
            "instance": module, "state_reg": reg, "width": width, "encoding": enc,
            "file": "fixture.sv", "states": states, "transitions": trs, "outputs": None,
            "simplifications": [], "provenance": {"engine": "l1-hybrid", "style": "two-process"},
            "checks": {k: v for k, v in checks.items()}, "status": "ok",
            "rejected_reason": None}


def fsm_onehot() -> dict:
    """One-hot, 5 states, self-loops, a long guard (> 40 chars), one semantic-only edge."""
    s = [_st("IDLE", 1, reset=True), _st("LOAD", 2), _st("RUN", 4), _st("WAIT", 8),
         _st("DONE", 16)]
    t = [_tr(0, "IDLE", "IDLE", "!start", line=40),
         _tr(1, "IDLE", "LOAD", "start", line=41),
         _tr(2, "LOAD", "RUN", "1", kind="always", line=45),
         _tr(3, "RUN", "RUN", "!cnt_done && !stall", line=48),
         _tr(4, "RUN", "WAIT", "stall && !(cnt_done || abort_req) && mem_busy_q", line=49),
         _tr(5, "WAIT", "RUN", "!mem_busy_q", line=52),
         _tr(6, "RUN", "DONE", "cnt_done", line=50),
         _tr(7, "DONE", "IDLE", "ack_i", line=55),
         _tr(8, "WAIT", "IDLE", "abort_req", seen=("semantic",))]
    return _fsm("fx_onehot", "seq_ctrl", "state_q", 5, "onehot", s, t,
                semantic={"semantic_check": "consistent-subset", "ok": True},
                yosys={"status": "agree", "forced": True},
                completeness={"status": "bounded(20)", "depth": 20})


def fsm_star_expanded() -> dict:
    """A 'default: if (err) state <= ERR' style edge already expanded to every source state,
    merged with the existing guard by || where a (src, dst) pair repeats; one unnamed and
    unreached state."""
    s = [_st("RED", 0, reset=True), _st("GREEN", 1), _st("YELLOW", 2), _st("ERR", 3),
         _st("S_5", 5, reached=False, unnamed=True)]
    t = [_tr(0, "RED", "GREEN", "timer_done && !err", line=30),
         _tr(1, "GREEN", "YELLOW", "timer_done && !err", line=31),
         _tr(2, "YELLOW", "RED", "timer_done && !err", line=32),
         _tr(3, "RED", "ERR", "err", line=28),
         _tr(4, "GREEN", "ERR", "err", line=28),
         _tr(5, "YELLOW", "ERR", "err", line=28),
         _tr(6, "ERR", "ERR", "err", line=28),
         _tr(7, "ERR", "RED", "!err && clear", line=34),
         _tr(8, "S_5", "ERR", "err", line=28),
         _tr(9, "S_5", "RED", "!err", seen=("yosys",))]
    g = _fsm("fx_star", "traffic", "light_q", 3, "binary", s, t,
             semantic={"semantic_check": "consistent", "ok": True},
             yosys={"status": "yosys_declined"},
             completeness={"status": "skipped(not requested)"})
    g["simplifications"] = [{"what": "'*' source expanded to 5 states", "reason": "fixture",
                             "lines": [{"file": "fixture.sv", "line": 28}]}]
    return g


def fsm_unknown_guard() -> dict:
    """Semantic-only FSM: unnamed states, guards unknown on two edges."""
    s = [_st("S_0", 0, reset=True, unnamed=True), _st("S_1", 1, unnamed=True),
         _st("S_3", 3, unnamed=True), _st("BUSY", 6)]
    t = [_tr(0, "S_0", "S_1", "go", kind="cube", seen=("semantic",)),
         _tr(1, "S_1", "S_3", "?", kind="unknown", seen=("semantic",)),
         _tr(2, "S_3", "BUSY", "1", kind="always", seen=("semantic",)),
         _tr(3, "BUSY", "S_0", "cnt == 4'd9", kind="cycles", seen=("semantic", "proof")),
         _tr(4, "BUSY", "BUSY", "?", kind="unknown", seen=("semantic",))]
    return _fsm("fx_unknown", "ctr_fsm", "ph", 3, "other", s, t,
                semantic={"semantic_check": "semantic-only", "ok": True},
                yosys={"status": "yosys_unparsed"})


FSMS = {"fsm_onehot": fsm_onehot, "fsm_star": fsm_star_expanded,
        "fsm_unknown": fsm_unknown_guard}

# --------------------------------------------------------------------------- timing


def _lane(lid, signal, width, role, period, phase, seq, *, iface=None, enum=None):
    """seq: {cycle: value} (only drawn cycles)."""
    vals = [{"cycle": c, "t": phase + c * period, "v": v} for c, v in sorted(seq.items())]
    return {"id": lid, "signal": signal, "width": width, "role": role, "interface": iface,
            "values": vals, "enum": enum}


def _stim():
    return {"kind": "generated", "tb_path": "runs/x/sim/tb_gen.sv", "seed": 1,
            "simulator": "iverilog", "version": "Icarus Verilog version 14.0 (stable)",
            "cmd": [], "warnings": [], "vcd_sha256": None}


def _expand(pts: dict, cycles: list[int]) -> dict:
    """Piecewise-constant: value of the last change point <= c for every drawn cycle."""
    out, cur = {}, None
    keys = sorted(pts)
    for c in cycles:
        for k in keys:
            if k <= c:
                cur = pts[k]
        out[c] = cur
    return out


def timing_single() -> dict:
    """valid/ready/data + an internal count, one gap (20 idle cycles), 2 arrows."""
    P, PH = 10, 5
    cyc = list(range(3, 11)) + list(range(31, 37))
    lanes = [
        _lane("l.0", "in_valid", 1, "valid", P, PH,
              _expand({3: "0", 4: "1", 7: "0", 32: "1", 34: "0"}, cyc), iface="if.in"),
        _lane("l.1", "in_ready", 1, "ready", P, PH,
              _expand({3: "1", 6: "0", 7: "1", 33: "1"}, cyc), iface="if.in"),
        _lane("l.2", "in_data", 8, "data", P, PH,
              _expand({3: "xx", 4: "a5", 5: "3c", 7: "xx", 32: "ff", 34: "xx"}, cyc),
              iface="if.in"),
        _lane("l.3", "count_q", 5, "reg", P, PH,
              _expand({3: "00", 5: "01", 6: "02", 33: "03"}, cyc)),
    ]
    arrows = [
        {"id": "a.0", "src": {"lane": "l.0", "cycle": 4, "t": 45},
         "dst": {"lane": "l.3", "cycle": 5, "t": 55}, "regs": 1, "kind": "next",
         "path": ["sync_fifo.in_valid", "sync_fifo.count_q"],
         "via_lines": [{"file": "sync_fifo.sv", "line": 33}]},
        {"id": "a.1", "src": {"lane": "l.3", "cycle": 6, "t": 65},
         "dst": {"lane": "l.1", "cycle": 6, "t": 65}, "regs": 0, "kind": "same",
         "path": ["sync_fifo.count_q", "sync_fifo.in_ready"], "via_lines": []},
    ]
    return {"schema_version": "timing-0.1", "id": "sync_fifo.if.in.first-fire",
            "design": "sync_fifo", "module": "sync_fifo", "interface": "if.in",
            "protocol": "VALID_READY", "scenario": "first-fire", "stimulus": _stim(),
            "domains": [{"id": "d.clk", "clock": "clk", "period": P, "phase": PH,
                         "lanes": lanes}],
            "windows": [{"t0": 35, "t1": 105, "reason": "first fire of in"},
                        {"t0": 315, "t1": 365, "reason": "second fire of in"}],
            "gaps": [{"after_t": 105, "until_t": 315, "cycles": {"d.clk": 20}}],
            "arrows": arrows, "simplifications": [], "checks": {}}


def timing_two_domain() -> dict:
    """wr clock period 10 / rd clock period 14, one gap, a cdc arrow through a sync pair."""
    PW, FW, PR, FR = 10, 5, 14, 7
    wc = list(range(0, 16)) + list(range(46, 56))
    rc = list(range(0, 11)) + list(range(33, 40))
    wr = [
        _lane("l.0", "wr_en", 1, "wr", PW, FW, _expand({0: "0", 2: "1", 4: "0", 47: "1",
                                                         48: "0"}, wc), iface="if.wr"),
        _lane("l.1", "wdata", 8, "data", PW, FW,
              _expand({0: "00", 2: "11", 3: "22", 4: "00", 47: "33", 48: "00"}, wc),
              iface="if.wr"),
        _lane("l.2", "wptr_gray", 4, "reg", PW, FW, _expand({0: "0", 3: "1", 4: "3", 48: "2"},
                                                             wc)),
    ]
    rd = [
        _lane("l.3", "wptr_gray_sync", 4, "reg", PR, FR,
              _expand({0: "0", 4: "1", 5: "3", 35: "2"}, rc)),
        _lane("l.4", "rd_en", 1, "rd", PR, FR, _expand({0: "0", 6: "1", 8: "0", 36: "1",
                                                         37: "0"}, rc), iface="if.rd"),
        _lane("l.5", "rdata", 8, "data", PR, FR,
              _expand({0: "xx", 6: "11", 7: "22", 8: "xx", 36: "33", 37: "xx"}, rc),
              iface="if.rd"),
    ]
    arrows = [
        {"id": "a.0", "src": {"lane": "l.0", "cycle": 2, "t": 25},
         "dst": {"lane": "l.2", "cycle": 3, "t": 35}, "regs": 1, "kind": "next",
         "path": ["afifo.wr_en", "afifo.wptr_gray"], "via_lines": []},
        {"id": "a.1", "src": {"lane": "l.2", "cycle": 3, "t": 35},
         "dst": {"lane": "l.3", "cycle": 4, "t": 63}, "regs": 2, "kind": "cdc",
         "path": ["afifo.wptr_gray", "afifo.wq1", "afifo.wptr_gray_sync"], "via_lines": []},
        {"id": "a.2", "src": {"lane": "l.4", "cycle": 6, "t": 91},
         "dst": {"lane": "l.5", "cycle": 6, "t": 91}, "regs": 0, "kind": "same",
         "path": ["afifo.rd_en", "afifo.rdata"], "via_lines": []},
    ]
    return {"schema_version": "timing-0.1", "id": "afifo.if.wr.cdc", "design": "afifo",
            "module": "afifo", "interface": "if.wr", "protocol": "FIFO", "scenario": "cdc",
            "stimulus": _stim(),
            "domains": [{"id": "d.wclk", "clock": "wclk", "period": PW, "phase": FW,
                         "lanes": wr},
                        {"id": "d.rclk", "clock": "rclk", "period": PR, "phase": FR,
                         "lanes": rd}],
            "windows": [{"t0": 5, "t1": 155, "reason": "first write and its read"},
                        {"t0": 465, "t1": 555, "reason": "second write"}],
            "gaps": [{"after_t": 155, "until_t": 465, "cycles": {"d.wclk": 30, "d.rclk": 22}}],
            "arrows": arrows, "simplifications": [], "checks": {}}


def timing_fsm_lane() -> dict:
    """uart_tx-like: handshake, FSM state lane with enum names, bit counter, serial out."""
    P, PH = 10, 5
    cyc = list(range(0, 16))
    enum = {"0": "S_IDLE", "1": "S_START", "2": "S_DATA", "3": "S_STOP"}
    lanes = [
        _lane("l.0", "tx_valid", 1, "valid", P, PH, _expand({0: "0", 2: "1", 3: "0"}, cyc),
              iface="if.tx"),
        _lane("l.1", "tx_ready", 1, "ready", P, PH, _expand({0: "1", 3: "0", 14: "1"}, cyc),
              iface="if.tx"),
        _lane("l.2", "tx_data", 8, "data", P, PH, _expand({0: "xx", 2: "5a", 3: "xx"}, cyc),
              iface="if.tx"),
        _lane("l.3", "state_q", 2, "state", P, PH,
              _expand({0: "0", 3: "1", 4: "2", 12: "3", 13: "0"}, cyc), enum=enum),
        _lane("l.4", "bit_cnt", 3, "reg", P, PH,
              _expand({0: "0", 5: "1", 6: "2", 7: "3", 8: "4", 9: "5", 10: "6", 11: "7",
                       12: "0"}, cyc)),
        _lane("l.5", "tx", 1, "serial", P, PH,
              _expand({0: "1", 3: "0", 4: "0", 5: "1", 6: "0", 8: "1", 10: "0", 12: "1"}, cyc)),
    ]
    arrows = [
        {"id": "a.0", "src": {"lane": "l.0", "cycle": 2, "t": 25},
         "dst": {"lane": "l.3", "cycle": 3, "t": 35}, "regs": 1, "kind": "next",
         "path": ["uart_tx.tx_valid", "uart_tx.state_q"], "via_lines": []},
        {"id": "a.1", "src": {"lane": "l.3", "cycle": 3, "t": 35},
         "dst": {"lane": "l.1", "cycle": 3, "t": 35}, "regs": 0, "kind": "same",
         "path": ["uart_tx.state_q", "uart_tx.tx_ready"], "via_lines": []},
        {"id": "a.2", "src": {"lane": "l.3", "cycle": 3, "t": 35},
         "dst": {"lane": "l.5", "cycle": 3, "t": 35}, "regs": 0, "kind": "same",
         "path": ["uart_tx.state_q", "uart_tx.tx"], "via_lines": []},
    ]
    return {"schema_version": "timing-0.1", "id": "uart_tx.if.tx.fsm", "design": "uart_tx",
            "module": "uart_tx", "interface": "if.tx", "protocol": "VALID_READY",
            "scenario": "fsm", "stimulus": _stim(),
            "domains": [{"id": "d.clk", "clock": "clk", "period": P, "phase": PH,
                         "lanes": lanes}],
            "windows": [{"t0": 5, "t1": 155, "reason": "one byte"}],
            "gaps": [], "arrows": arrows, "simplifications": [], "checks": {}}


TIMINGS = {"timing_single": timing_single, "timing_two_domain": timing_two_domain,
           "timing_fsm_lane": timing_fsm_lane}
