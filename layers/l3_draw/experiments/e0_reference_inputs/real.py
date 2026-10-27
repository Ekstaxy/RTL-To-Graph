"""Cases drafted by hand from five reference figures (not from RTL).

Each function returns (Diagram, hints). What the figure shows decides blocks and nets;
port names and every width are my assumption, because figures do not carry them. Lines
that could not be followed with confidence are listed in each docstring. Treat these as
realistic test inputs, not as a description of the real IP.

Hints are experiment-local (no contract yet). Field names come from the design-space
document, S3: `stage_index`, `stage_boundary`, `lane`, `flow_role`.
"""

from __future__ import annotations

from gen import _Builder
from spec import Diagram

Hints = dict[str, dict[str, dict[str, object]]]


class _B(_Builder):
    """Builder with short helpers: `io` for boundary ports, `wire` for a net by port name."""

    def __init__(self) -> None:
        super().__init__()
        self.hints: Hints = {"blocks": {}, "sinks": {}}
        self._n = 0

    def blk(self, name: str, label: str, kind: str, parent: str | None = None, **hint) -> str:
        bid = self.block(f"b.{name}", label, kind, f"b.{parent}" if parent else None)
        if hint:
            self.hints["blocks"][bid] = hint
        return bid

    def wire(
        self,
        src: str,
        dsts: list[str],
        width: int = 1,
        cls: str = "data",
        name: str | None = None,
        feedback: tuple[str, ...] = (),
    ) -> None:
        """Ports are 'block.port' (created on first use) or 'in:name' / 'out:name'."""
        self._n += 1
        name = name or src.replace("in:", "").replace(".", "_")
        s = self._port(src, "output", width, cls)
        ts = [self._port(t, "input", width, cls) for t in dsts]
        self.net(name, s, ts, width, cls)
        for t in feedback:
            self.hints["sinks"][f"n.{name}|{self._pid(t)}"] = {"flow_role": "feedback"}

    @staticmethod
    def _pid(ref: str) -> str:
        if ref.startswith(("in:", "out:")):
            return "p." + ref.split(":")[1]
        return "b." + ref

    def _port(self, ref: str, direction: str, width: int, cls: str) -> str:
        pid = self._pid(ref)
        if any(p.id == pid for p in self.ports):
            return pid
        if ref.startswith("in:"):
            return self.port(None, ref[3:], "input", width, cls)
        if ref.startswith("out:"):
            return self.port(None, ref[4:], "output", width, cls)
        owner, name = ref.rsplit(".", 1)
        return self.port("b." + owner, name, direction, width, cls)


def rv_timer() -> tuple[Diagram, Hints]:
    """OpenTitan rv_timer/doc/timer_block_diagram.svg. 5 blocks, small feedback loop.

    The figure draws "tick gen" as a stacked box (one per hart); the format has no
    replication field, so it is a single block here.
    """
    b = _B()
    b.blk("tick", "tick gen", "comb", stage_index=1)
    b.blk("add", "+", "adder", stage_index=1)
    b.blk("mux", "MUX", "mux", stage_index=1)
    b.blk("mtime", "mtime", "register", stage_boundary=1)
    b.blk("cmp", ">=", "comparator", stage_index=2)
    b.wire("in:clk_fixed", ["tick.clk"], 1, "clock")
    b.wire("in:prescaler", ["tick.prescaler"], 12)
    b.wire("in:step", ["add.b"], 8)
    b.wire("tick.tick", ["mux.sel"], 1, "control")
    b.wire("add.y", ["mux.in1"], 64)
    b.wire("mux.y", ["mtime.d"], 64)
    b.wire(
        "mtime.q", ["add.a", "mux.in0", "cmp.a"], 64, name="mtime", feedback=("add.a", "mux.in0")
    )
    b.wire("in:mtimecmp", ["cmp.b"], 64)
    b.wire("cmp.y", ["out:expired"], 1, "control")
    return b.build(), b.hints


def uart() -> tuple[Diagram, Hints]:
    """OpenTitan uart/doc/block_diagram.svg. 13 blocks, TX path over RX path, two loopbacks.

    Not followed: `cio_tx_en_o` (label only, no driver drawn). The ten interrupt outputs
    are one arrow in the figure and one 10-bit net here. The dashed lines from the FIFOs
    and the baud clock into "error checking, status" are drawn as status nets.
    """
    b = _B()
    b.blk("reg", "register file", "regfile", lane="control")
    b.blk("baud", "GEN baud", "comb", stage_index=1)
    b.blk("txfifo", "32x8 TX FIFO", "fifo", stage_index=1)
    b.blk("pargen", "parity gen + framing", "comb", stage_index=2)
    b.blk("txshift", "serial shift", "register", stage_boundary=2)
    b.blk("txmux", "MUX", "mux", stage_index=3)
    b.blk("sync", "sync", "register", stage_boundary=0)
    b.blk("filter", "input filter", "comb", stage_index=1)
    b.blk("rxmux", "MUX", "mux", stage_index=1)
    b.blk("rxshift", "serial shift", "register", stage_boundary=1)
    b.blk("parchk", "parity check", "comb", stage_index=2)
    b.blk("rxfifo", "64x8 RX FIFO", "fifo", stage_index=2)
    b.blk("status", "error checking, status", "comb", stage_index=3)
    b.wire("in:tl_i", ["reg.tl_i"], 109, "bus")
    b.wire("reg.tl_o", ["out:tl_o"], 66, "bus")
    b.wire("reg.nco", ["baud.nco"], 16, "control")
    b.wire("baud.tick", ["txshift.tick", "rxshift.tick", "status.tick"], 1, "control", "baud_clk")
    b.wire("reg.wdata", ["txfifo.d"], 8)
    b.wire("txfifo.q", ["pargen.d"], 8)
    b.wire("pargen.y", ["txshift.d"], 11)
    b.wire("txshift.q", ["txmux.in1", "rxmux.in1"], 1, name="tx")
    b.wire("txmux.y", ["out:cio_tx_o"], 1)
    b.wire("reg.llpbk", ["txmux.sel"], 1, "control")
    b.wire("reg.slpbk", ["rxmux.sel"], 1, "control")
    b.wire("reg.nf", ["filter.en"], 1, "control")
    b.wire("in:cio_rx_i", ["sync.d"], 1)
    b.wire("sync.q", ["filter.d"], 1)
    b.wire("filter.y", ["rxmux.in0", "txmux.in0"], 1, name="rx")
    b.wire("rxmux.y", ["rxshift.d"], 1)
    b.wire("rxshift.q", ["parchk.d"], 11)
    b.wire("parchk.y", ["rxfifo.d"], 8)
    b.wire("rxfifo.q", ["reg.rdata"], 8)
    b.wire("txfifo.lvl", ["status.tx_lvl"], 6, "status")
    b.wire("rxfifo.lvl", ["status.rx_lvl"], 7, "status")
    b.wire("parchk.err", ["status.par_err"], 1, "status")
    b.wire("rxshift.err", ["status.frame_err"], 1, "status")
    b.wire("reg.ctrl", ["status.ctrl"], 32, "control")
    b.wire("status.state", ["reg.intr_state"], 10, "status")
    b.wire("status.intr", ["out:intr_o"], 10, "control")
    return b.build(), b.hints


def hmac() -> tuple[Diagram, Hints]:
    """OpenTitan hmac/doc/hmac_block_diagram.svg. 8 blocks, one container, digest feedback.

    The two thick vertical bars in the figure are merge points; they are muxes here.
    The select lines of those muxes are not in the figure and not in this case.
    """
    b = _B()
    b.blk("reg", "reg. module", "regfile", stage_index=0)
    b.blk("packer", "packer", "comb", stage_index=1)
    b.blk("fmux", "MUX", "mux", stage_index=1)
    b.blk("fifo", "32x32b FIFO", "fifo", stage_index=2)
    b.blk("core", "HMAC core", "group")
    b.blk("keypad", "key_padding", "comb", "core", stage_index=3)
    b.blk("mmux", "MUX", "mux", "core", stage_index=3)
    b.blk("lenconv", "length_conversion", "comb", "core", stage_index=3)
    b.blk("sha", "SHA-2 multi-mode prim", "comb", stage_index=4)
    b.wire("in:tl_i", ["reg.tl_i"], 109, "bus")
    b.wire("reg.tl_o", ["out:tl_o"], 66, "bus")
    b.wire("reg.secret_key", ["keypad.key"], 1024)
    b.wire("reg.wdata", ["packer.d"], 32)
    b.wire("packer.y", ["fmux.in0"], 32)
    b.wire("fmux.y", ["fifo.d"], 32)
    b.wire("fifo.q", ["mmux.in2"], 32)
    b.wire("keypad.ipad", ["mmux.in0"], 1024)
    b.wire("keypad.opad", ["mmux.in1"], 1024)
    b.wire("mmux.y", ["sha.message"], 32)
    b.wire("packer.len", ["lenconv.d"], 64)
    b.wire("lenconv.y", ["sha.message_length"], 128)
    b.wire("sha.digest", ["reg.digest", "fmux.in1"], 32, feedback=("reg.digest", "fmux.in1"))
    return b.build(), b.hints


def plic() -> tuple[Diagram, Hints]:
    """OpenTitan rv_plic/doc/block_diagram.svg. 6 blocks, registers below the datapath.

    The figure repeats the AND/mux pair per interrupt source and the "Process" box per
    target; one of each is kept. `ie` enters the AND gate from the registers.
    """
    b = _B()
    b.blk("gw", "Gateway", "comb", stage_index=1)
    b.blk("proc", "Process", "group")
    b.blk("and", "AND", "gate", "proc", stage_index=2)
    b.blk("pmux", "MUX", "mux", "proc", stage_index=2)
    b.blk("max", "FIND_MAX", "comb", "proc", stage_index=3)
    b.blk("reg", "registers", "regfile", lane="control")
    b.wire("in:intr_src_i", ["gw.src"], 32)
    b.wire("in:tl_i", ["reg.tl_i"], 109, "bus")
    b.wire("reg.tl_o", ["out:tl_o"], 66, "bus")
    b.wire("gw.ip", ["and.ip", "reg.ip"], 32)
    b.wire("reg.le", ["gw.le"], 32, "control")
    b.wire("reg.claim", ["gw.claim"], 32, "control")
    b.wire("reg.complete", ["gw.complete"], 32, "control")
    b.wire("reg.ie", ["and.ie"], 32, "control")
    b.wire("reg.priority", ["pmux.prio"], 96, "control")
    b.wire("and.y", ["pmux.sel"], 32)
    b.wire("pmux.y", ["max.prio"], 96)
    b.wire("reg.threshold", ["max.threshold"], 3, "control")
    b.wire("max.irq", ["out:irq_o"], 1, "control")
    b.wire("max.irq_id", ["out:irq_id_o", "reg.irq_id"], 6, feedback=("reg.irq_id",))
    return b.build(), b.hints


def ibex() -> tuple[Diagram, Hints]:
    """Ibex doc/03_reference/images/blockdiagram.svg. 22 blocks, 4 containers, 2 levels.

    The figure has about 40 thin lines and no signal names. Blocks and containers follow
    the figure. Nets follow the lines I could trace; the rest are a plausible reading of a
    two-stage RISC-V core, so the net list is close to the figure but not identical. The
    unlabelled tall box in Instruction Fetch is called "fetch FIFO" and the unlabelled box
    in Writeback "WB stage"; both names are guesses. Clock triangles in the figure are
    the single `clk` net.
    """
    b = _B()
    b.blk("rf", "Register File", "regfile", lane="control")
    b.blk("if", "Instruction Fetch", "stage")
    b.blk("pc", "PC", "register", "if", stage_index=1)
    b.blk("icache", "ICache", "memory", "if", stage_index=1)
    b.blk("prefetch", "Prefetch Buffer", "fifo", "if", stage_index=1)
    b.blk("ffifo", "fetch FIFO", "register", "if", stage_boundary=1)
    b.blk("cdec", "Compressed Instruction Decoder", "comb", "if", stage_index=1)
    b.blk("pmp_i", "PMP Check", "comb", stage_index=2)
    b.blk("idex", "Decode and Execute", "stage")
    b.blk("ctrl", "Controller", "controller", "idex", stage_index=2)
    b.blk("dec", "Decoder", "comb", "idex", stage_index=2)
    b.blk("csr", "CSRs", "regfile", "idex", stage_index=2)
    b.blk("opmux", "MUX", "mux", "idex", stage_index=2)
    b.blk("ex", "Execute", "group", "idex")
    b.blk("alu", "ALU", "comb", "ex", stage_index=2)
    b.blk("muldiv", "Mul/Div", "comb", "ex", stage_index=2)
    b.blk("csrmux", "MUX", "mux", "idex", stage_index=2)
    b.blk("wb", "Writeback", "stage")
    b.blk("wbreg", "WB stage", "register", "wb", stage_boundary=2)
    b.blk("wbmux", "MUX", "mux", "wb", stage_index=3)
    b.blk("lsu", "LSU", "comb", stage_index=3)
    b.blk("pmp_d", "PMP Check", "comb", stage_index=3)

    b.wire("in:clk_i", [f"{r}.clk" for r in ("pc", "ffifo", "csr", "wbreg", "rf")], 1, "clock")
    b.wire("in:debug_req_i", ["ctrl.debug_req"], 1, "control")
    b.wire("in:instr_rdata_i", ["icache.rdata", "prefetch.rdata"], 32, "bus")
    b.wire("pc.q", ["icache.addr", "prefetch.addr", "ffifo.pc"], 32, name="pc")
    b.wire("icache.instr", ["ffifo.cache"], 32)
    b.wire("prefetch.instr", ["ffifo.pref"], 32)
    b.wire("prefetch.req", ["out:instr_addr_o"], 32, "bus")
    b.wire("ffifo.raw", ["cdec.instr"], 32)
    b.wire("cdec.y", ["ffifo.decomp"], 32)
    b.wire("ffifo.instr", ["pmp_i.addr", "dec.instr"], 32, name="instr")
    b.wire("ffifo.pc_id", ["opmux.pc"], 32)
    b.wire("pmp_i.err", ["dec.pmp_err"], 1, "control")
    b.wire("dec.ctl", ["ctrl.dec"], 8, "control")
    b.wire("ctrl.pc_set", ["pc.set"], 1, "control", feedback=("pc.set",))
    b.wire("ctrl.stall", ["dec.stall", "csr.stall"], 1, "control")
    b.wire("ctrl.flush", ["wbreg.flush", "lsu.flush"], 1, "control")
    b.wire("dec.imm", ["opmux.imm"], 32)
    b.wire("dec.rf_raddr", ["rf.raddr"], 10, "control")
    b.wire("rf.rdata", ["opmux.reg", "lsu.wdata"], 32, name="rf_rdata")
    b.wire("opmux.y", ["alu.a", "muldiv.a"], 32)
    b.wire("dec.alu_op", ["alu.op", "muldiv.op"], 7, "control")
    b.wire(
        "alu.y", ["csrmux.in1", "lsu.addr", "pc.target"], 32, name="alu", feedback=("pc.target",)
    )
    b.wire("muldiv.y", ["alu.md"], 34)
    b.wire("dec.csr_op", ["csr.op"], 2, "control")
    b.wire("csr.rdata", ["csrmux.in0"], 32)
    b.wire("csrmux.y", ["wbreg.d"], 32)
    b.wire("wbreg.q", ["wbmux.in0", "opmux.fwd"], 32, name="wb_fwd", feedback=("opmux.fwd",))
    b.wire("lsu.rdata", ["wbmux.in1"], 32)
    b.wire("wbmux.y", ["rf.wdata"], 32, feedback=("rf.wdata",))
    b.wire("lsu.req", ["pmp_d.addr"], 32)
    b.wire("pmp_d.ok", ["out:data_addr_o"], 32, "bus")
    b.wire("lsu.data_wdata", ["out:data_wdata_o"], 32, "bus")
    b.wire("in:data_rdata_i", ["lsu.data_rdata"], 32, "bus")
    return b.build(), b.hints


REAL = {"rv_timer": rv_timer, "uart": uart, "hmac": hmac, "plic": plic, "ibex": ibex}
