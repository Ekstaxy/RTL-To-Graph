"""Inputs for e2: cases transcribed from the four figures in the memo, Earl Grey from the
public OpenTitan figure (from memory), a systolic array, and a 60-node DAG for the CP-SAT
bench; plus the e0 seeds that already cover classes A-E.

Every case is e0 format (spec.py 0.1.0) with e0-style hints, plus a *sidecar* JSON that
holds what the format has no field for (ADR candidates, see README):

    {"nodes": {"<block id>": {"role": "bus|crossbar|noc",
                              "replicate": {"count": N, "shape": "stack"},
                              "view_level": "A".."E", "expand": true}},
     "arrays": [{"id": "pe", "shape": [rows, cols], "members": [[ids per row], ...]}],
     "expected": {"": "D", "<container id>": "C"},   # hand-assigned class per container
     "aspect": 1.78}

Port names and widths are assumed; the figures do not carry them (same caveat as e0's
real.py). Replicated units (x4, x32, 16 banks) are written once with `replicate`, the way
x1's bridge folds generate arrays before drawing, so L3 never hides a block.

    uv run --package rtl2d-l3 python layers/l3_draw/experiments/e2_class_engines/inputs.py --check
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import e1lib  # noqa: F401  (puts e0 and e1 on sys.path)
from e1lib import E0_INPUTS, RUNS, spec
from real import _B
from topo import comb_dag

Case = tuple[spec.Diagram, dict, dict]  # diagram, hints, sidecar


def _side(expected: dict[str, str], nodes: dict | None = None, arrays: list | None = None):
    return {"nodes": nodes or {}, "arrays": arrays or [], "expected": expected, "aspect": 1.78}


# ----------------------------------------------------------------------------- memo figures
def fig_system() -> Case:
    """Memo figure 3: CPU + task scheduler + memory controller + HBM/DDR + N computing cores
    (instruction scheduler, MMU, MPE, SFU). Class C, depth 2, colour = type."""
    b = _B()
    b.blk("cpu", "CPU", "cpu")
    b.blk("sched", "Task Scheduler", "controller")
    b.blk("memctl", "Memory Controller", "memory")
    b.blk("hbm", "HBM", "memory")
    b.blk("ddr", "DDR", "memory")
    b.blk("core", "Computing Core", "group")
    b.blk("isched", "Instruction Scheduler", "controller", "core")
    b.blk("mmu", "Memory Management Unit (MMU)", "memory", "core")
    b.blk("mpe", "Matrix Processing Engine (MPE)", "comb", "core")
    b.blk("sfu", "Special Function Unit (SFU)", "comb", "core")
    b.wire("cpu.cmd", ["sched.cmd"], 64, "bus")
    b.wire("sched.status", ["cpu.status"], 32, "bus", feedback=("cpu.status",))
    b.wire("sched.mem_req", ["memctl.req"], 64, "bus")
    b.wire("memctl.hbm_req", ["hbm.req"], 128, "bus")
    b.wire("hbm.rsp", ["memctl.hbm_rsp"], 128, "bus", feedback=("memctl.hbm_rsp",))
    b.wire("memctl.ddr_req", ["ddr.req"], 64, "bus")
    b.wire("ddr.rsp", ["memctl.ddr_rsp"], 64, "bus", feedback=("memctl.ddr_rsp",))
    b.wire("sched.task", ["isched.task"], 64, "bus")
    b.wire("memctl.data", ["mmu.data"], 256, "bus")
    b.wire("mmu.wr", ["memctl.wr"], 256, "bus", feedback=("memctl.wr",))
    b.wire("isched.op_mmu", ["mmu.op"], 16, "control")
    b.wire("isched.op_mpe", ["mpe.op"], 16, "control")
    b.wire("isched.op_sfu", ["sfu.op"], 16, "control")
    b.wire("mmu.a", ["mpe.a"], 256)
    b.wire("mpe.r", ["mmu.r"], 256, feedback=("mmu.r",))
    b.wire("mmu.b", ["sfu.b"], 256)
    b.wire("sfu.r", ["mmu.rs"], 256, feedback=("mmu.rs",))
    side = _side({"": "C", "b.core": "C"},
                 {"b.core": {"replicate": {"count": 3, "shape": "stack"}}})
    return b.build(), b.hints, side


def fig_sfu() -> Case:
    """Memo figure 2: the SFU. Instruction control (3 units), micro-op controller, remote
    access, in/out queues and the MISC ALU (N element-wise units + reduction). Class C,
    depth 3, colour = function."""
    b = _B()
    b.blk("isched", "Inst. Scheduler", "controller")
    b.blk("gbuf", "Global Buffer", "memory")
    b.blk("sfu", "SFU", "group")
    b.blk("ictrl", "Inst. Ctrl", "group", "sfu")
    b.blk("iq", "Inst. Queue + Ctrl", "fifo", "ictrl")
    b.blk("ploader", "Param Loader", "comb", "ictrl")
    b.blk("dma", "DMA Ctrl", "controller", "ictrl")
    b.blk("uopc", "Micro-Op Controller", "controller", "sfu")
    b.blk("remote", "Remote SFU Access", "comb", "sfu")
    b.blk("oq", "Output Queue", "fifo", "sfu")
    b.blk("inq", "Input Queue", "fifo", "sfu")
    b.blk("misc", "MISC ALU", "group", "sfu")
    b.blk("epu", "Element-wise Processing Unit", "comb", "misc")
    b.blk("redu", "Reduction Unit (Param Reg)", "comb", "misc")
    b.wire("isched.inst", ["iq.inst", "ploader.inst", "dma.inst"], 64, "bus")
    b.wire("iq.uop", ["uopc.uop"], 32)
    b.wire("ploader.param", ["uopc.param"], 32)
    b.wire("dma.ctl", ["uopc.dma"], 8, "control")
    b.wire("uopc.req", ["remote.req"], 64, "bus")
    b.wire("remote.rsp", ["uopc.rsp"], 64, "bus", feedback=("uopc.rsp",))
    b.wire("remote.out", ["out:remote_sfu"], 64, "bus")
    b.wire("uopc.cmd", ["epu.cmd", "redu.cmd"], 16, "control")
    b.wire("gbuf.rd", ["inq.d"], 256, "bus")
    b.wire("inq.q", ["epu.a"], 256)
    b.wire("epu.y", ["redu.a"], 256)
    b.wire("redu.y", ["oq.d"], 256)
    b.wire("oq.q", ["gbuf.wr"], 256, "bus", feedback=("gbuf.wr",))
    side = _side({"": "C", "b.sfu": "C", "b.ictrl": "C", "b.misc": "C"},
                 {"b.epu": {"replicate": {"count": 4, "shape": "stack"}}})
    return b.build(), b.hints, side


def fig_gs_soc() -> Case:
    """Memo figure 1: the 3D-Gaussian SoC. Top controller (TileLink bar), SPU (local DBUS
    bar), a full-width interconnect, 4 global memories (local NoC bar), 4 SCGS clusters.
    Class D, depth 3, colour = subsystem. Zoom panels are fig_gs_mac / fig_gs_edc."""
    b = _B()
    # top controller
    b.blk("topctl", "Top Controller", "group")
    for n, lbl in (("gpio", "GPIO"), ("uart", "UART"), ("jtag", "JTAG"), ("hyper", "Hyper Bus IF")):
        b.blk(n, lbl, "peripheral", "topctl")
        b.wire(f"in:{n}_i", [f"{n}.pad_i"], 8)
        b.wire(f"{n}.pad_o", [f"out:{n}_o"], 8)
    b.blk("tilelink", "TileLink", "bus", "topctl")
    b.blk("rvtile", "RISC-V Tile", "cpu", "topctl")
    b.blk("l2", "L2 Cache (16 KB)", "memory", "topctl")
    b.blk("axibus", "AXI Bus", "bus", "topctl")
    b.blk("nocif", "NoC AXI I/F", "comb", "topctl")
    for n in ("gpio", "uart", "jtag", "hyper", "rvtile", "l2", "axibus"):
        b.wire(f"{n}.tl_req", [f"tilelink.{n}_req"], 32, "bus")
        b.wire(f"tilelink.{n}_rsp", [f"{n}.tl_rsp"], 32, "bus", feedback=(f"{n}.tl_rsp",))
    b.wire("axibus.noc_req", ["nocif.req"], 64, "bus")
    b.wire("nocif.rsp", ["axibus.noc_rsp"], 64, "bus", feedback=("axibus.noc_rsp",))
    # interconnect
    b.blk("ic", "Interconnect Network", "bus")
    b.wire("in:ic_l_i", ["ic.pad_l_i"], 64, "bus")
    b.wire("ic.pad_l_o", ["out:ic_l_o"], 64, "bus")
    b.wire("in:ic_r_i", ["ic.pad_r_i"], 64, "bus")
    b.wire("ic.pad_r_o", ["out:ic_r_o"], 64, "bus")
    b.wire("nocif.ic_req", ["ic.tc_req"], 64, "bus")
    b.wire("ic.tc_rsp", ["nocif.ic_rsp"], 64, "bus", feedback=("nocif.ic_rsp",))
    # SPU
    b.blk("spu", "Surface Perception Unit (SPU)", "group")
    b.blk("gob", "Gaussian Order Buffer", "memory", "spu")
    b.blk("gsu", "Gaussian Sorting Unit", "comb", "spu")
    b.blk("src", "Surface Rasterization Core", "comb", "spu")
    b.blk("smem", "Surface MEM (256 KB)", "group", "spu")
    b.blk("osurf", "Origin Surface", "memory", "smem")
    b.blk("dsurf", "Deformed Surface", "memory", "smem")
    b.blk("dbus", "Local DBUS", "bus", "spu")
    b.blk("sext", "Surface Extractor", "group", "spu")
    b.blk("march", "MarchCube Engine", "comb", "sext")
    b.blk("cgcu", "Coplanar-Gaussian Clustering Unit", "comb", "sext")
    b.blk("sdef", "Surface Deformer", "group", "spu")
    b.blk("arap", "ARAP-Tuning Engine", "comb", "sdef")
    b.blk("hci", "HC Initializer", "comb", "sdef")
    b.wire("gob.out", ["gsu.in"], 128)
    b.wire("gsu.out", ["src.in"], 128)
    for n in ("gob", "src", "osurf", "dsurf", "march", "cgcu", "arap", "hci"):
        b.wire(f"{n}.d_req", [f"dbus.{n}_req"], 64, "bus")
        b.wire(f"dbus.{n}_rsp", [f"{n}.d_rsp"], 64, "bus", feedback=(f"{n}.d_rsp",))
    b.wire("dbus.ic_req", ["ic.spu_req"], 64, "bus")
    b.wire("ic.spu_rsp", ["dbus.ic_rsp"], 64, "bus", feedback=("dbus.ic_rsp",))
    # global memory (x4)
    b.blk("gmem", "Global Memory #0", "group")
    b.blk("lnoc", "Local NoC", "bus", "gmem")
    b.blk("router", "Network Router", "comb", "gmem")
    b.blk("gsram", "Global SRAM (128 KB)", "memory", "gmem")
    b.blk("simd", "SIMD", "comb", "gmem")
    b.blk("wuu", "Weight Update Unit", "comb", "gmem")
    for n in ("router", "gsram", "simd", "wuu"):
        b.wire(f"{n}.n_req", [f"lnoc.{n}_req"], 64, "bus")
        b.wire(f"lnoc.{n}_rsp", [f"{n}.n_rsp"], 64, "bus", feedback=(f"{n}.n_rsp",))
    b.wire("router.ic_req", ["ic.gm_req"], 64, "bus")
    b.wire("ic.gm_rsp", ["router.ic_rsp"], 64, "bus", feedback=("router.ic_rsp",))
    # SCGS cluster (x4)
    b.blk("scgs", "SCGS Cluster #0", "group")
    b.blk("sram", "SRAM (208 KB)", "memory", "scgs")
    for i in range(4):
        b.blk(f"rama{i}", f"RAMA #{i}", "comb", "scgs")
    b.blk("aggr", "Aggregator", "comb", "scgs")
    b.blk("edc", "Error-Direction Cache (48 KB)", "memory", "scgs")
    b.blk("trilin", "Trilinear Interpolator", "comb", "scgs")
    b.blk("vru", "Volume Rendering Unit", "group", "scgs")
    b.blk("gtrans", "Gaussian Transformer", "comb", "vru")
    b.blk("proj2d", "2D Projection Block", "comb", "vru")
    b.blk("graster", "Gaussian Rasterizer", "comb", "vru")
    b.wire("sram.ic_req", ["ic.sc_req"], 64, "bus")
    b.wire("ic.sc_rsp", ["sram.ic_rsp"], 64, "bus", feedback=("sram.ic_rsp",))
    b.wire("sram.d", [f"rama{i}.a" for i in range(4)], 256)
    for i in range(4):
        b.wire(f"rama{i}.y", [f"aggr.i{i}"], 64)
    b.wire("aggr.y", ["edc.in"], 64)
    b.wire("edc.out", ["trilin.in"], 64)
    b.wire("trilin.out", ["gtrans.in"], 64)
    b.wire("gtrans.out", ["proj2d.in"], 64)
    b.wire("proj2d.out", ["graster.in"], 64)
    b.wire("graster.out", ["sram.wb"], 64, feedback=("sram.wb",))
    nodes = {
        "b.ic": {"role": "noc"}, "b.tilelink": {"role": "bus"}, "b.axibus": {"role": "bus"},
        "b.dbus": {"role": "bus"}, "b.lnoc": {"role": "bus"},
        "b.gmem": {"replicate": {"count": 4, "shape": "stack"}},
        "b.scgs": {"replicate": {"count": 4, "shape": "stack"}},
        "b.rama0": {"expand": True}, "b.edc": {"expand": True},
    }
    expected = {"": "D", "b.topctl": "D", "b.spu": "D", "b.smem": "C", "b.sext": "C",
                "b.sdef": "C", "b.gmem": "D", "b.scgs": "C", "b.vru": "C"}
    return b.build(), b.hints, _side(expected, nodes)


def fig_gs_mac() -> Case:
    """Memo figure 1, zoom panel A: reconfigurable ALP-based MAC array (32x32). A column of
    32 RFM + 16b buffers feeding one fused FP-MAC column. Class B (chain of operators)."""
    b = _B()
    b.blk("col", "Column #0", "group")
    b.blk("rfm", "RFM 0..31 (16b-BUF)", "regfile", "col")
    b.blk("hamat", "HAMAT", "comb", "col")
    b.blk("fmac", "Fused FP-MAC Column", "group")
    b.blk("rfmcol", "RFM Column", "regfile", "fmac")
    b.blk("reggate", "Register Gating", "gate", "fmac")
    b.blk("lsbenc", "LSB Encoder", "comb", "fmac")
    b.blk("linebuf", "Line Buffer (16b x 32)", "fifo", "fmac")
    b.blk("shmsb", "Shifter-based MSB AT", "adder", "fmac")
    b.blk("ormsb", "OR-based MSB AT", "gate", "fmac")
    b.blk("cgl", "Compensate & Gather Logic", "adder", "fmac")
    b.wire("in:act", ["rfm.d"], 16)
    b.wire("rfm.q", ["hamat.a"], 16)
    b.wire("hamat.y", ["rfmcol.a"], 16)
    b.wire("rfmcol.y", ["reggate.a", "lsbenc.a"], 16)
    b.wire("reggate.y", ["linebuf.a"], 16)
    b.wire("lsbenc.y", ["shmsb.a", "ormsb.a"], 8)
    b.wire("linebuf.y", ["shmsb.b"], 16)
    b.wire("shmsb.y", ["cgl.a"], 24)
    b.wire("ormsb.y", ["cgl.b"], 8)
    b.wire("cgl.y", ["out:result"], 32)
    b.wire("in:clk", ["rfm.clk", "rfmcol.clk", "linebuf.clk"], 1, "clock")
    nodes = {"b.col": {"replicate": {"count": 32, "shape": "stack"}},
             "b.rfm": {"replicate": {"count": 32, "shape": "stack"}}}
    return b.build(), b.hints, _side({"": "B", "b.col": "B", "b.fmac": "B"}, nodes)


def fig_gs_edc() -> Case:
    """Memo figure 1, zoom panel B: error-direction cache. Pattern matcher, cache update
    control, error generator, 4 cache memories (key buffer + value cache). Class C."""
    b = _B()
    b.blk("spm", "Sparsity Pattern Matcher", "comb")
    b.blk("cucu", "Cache Update Control Unit", "controller")
    b.blk("errgen", "Error Generator", "comb")
    b.blk("cmem", "Cache Memory", "group")
    b.blk("keybuf", "Key Buffer (72b x 64)", "memory", "cmem")
    b.blk("vcache", "Value Cache (12 KB)", "memory", "cmem")
    b.wire("in:addr", ["spm.a"], 32)
    b.wire("spm.hit", ["cucu.hit"], 4, "control")
    b.wire("cucu.upd_k", ["keybuf.w"], 72)
    b.wire("cucu.upd_v", ["vcache.w"], 64)
    b.wire("keybuf.k", ["spm.k"], 72, feedback=("spm.k",))
    b.wire("vcache.v", ["errgen.v"], 64)
    b.wire("errgen.e", ["out:err"], 64)
    nodes = {"b.cmem": {"replicate": {"count": 4, "shape": "stack"}}}
    return b.build(), b.hints, _side({"": "C", "b.cmem": "C"}, nodes)


def fig_sparse_core() -> Case:
    """Memo figure 4: sparse accelerator core with LDO / level shifter / DCO outside, and
    inside: controller, two bit-mask decoders (SRAM banks + sparse decoder + mux), MAC unit,
    post-processing chain, bit-mask encoder, special function unit. Class C with local B."""
    b = _B()
    b.blk("ldo", "LDO PMOS headers", "analog")
    b.blk("buf", "BUF", "gate")
    b.blk("csr", "CSR", "regfile")
    b.blk("ls", "LS", "analog")
    b.blk("dco", "DCO", "analog")
    b.blk("core", "Accelerator Core", "group")
    b.blk("ctrl", "Controller", "controller", "core")
    for k in (0, 1):
        b.blk(f"dec{k}", f"Bit-mask Decoder {k}", "group", "core")
        b.blk(f"msram{k}", "Mask SRAM (32KB)", "memory", f"dec{k}")
        b.blk(f"dsram{k}", "Data SRAM (256KB)", "memory", f"dec{k}")
        b.blk(f"sdec{k}", "Sparse Decoder", "comb", f"dec{k}")
        b.blk(f"mux{k}", "MUX", "mux", f"dec{k}")
    b.blk("mac", "MAC Unit", "group", "core")
    b.blk("fp4", "FP4 Datapaths", "comb", "mac")
    b.blk("fp8", "FP8 Datapaths", "comb", "mac")
    b.blk("acc", "Accumulation Unit", "adder", "mac")
    b.blk("post", "Post-Processing", "group", "core")
    b.blk("expshift", "FP Exponent Shift", "comb", "post")
    b.blk("bias", "Bias Add", "adder", "post")
    b.blk("relu", "RELU", "comb", "post")
    b.blk("trunc", "Truncate", "comb", "post")
    b.blk("enc", "Bit-mask Encoder", "group", "core")
    b.blk("maskb", "Mask", "register", "enc")
    b.blk("datab", "Data", "register", "enc")
    b.blk("senc", "Sparse Encoder", "comb", "enc")
    b.blk("muxe", "MUX", "mux", "enc")
    b.blk("sfu", "Special Function Unit", "group", "core")
    b.blk("ebc", "Entropy-Based Computations", "group", "sfu")
    b.blk("vfs", "V/F Scaling", "comb", "ebc")
    b.blk("mpp", "Mixed-Precision Predication", "comb", "ebc")
    b.blk("eea", "Early Exit Assessment", "comb", "ebc")
    b.blk("auxbuf", "Auxiliary Buffer (32KB)", "memory", "sfu")
    b.blk("vflut", "V/F Scaling LUT", "memory", "sfu")
    b.blk("amask", "Attention Mask", "memory", "sfu")
    b.blk("lnparam", "LayerNorm Params", "memory", "sfu")
    b.blk("ewadd", "Elem-Wise Add", "adder", "sfu")
    b.blk("lnorm", "Layer Normalization", "comb", "sfu")
    b.blk("softmax", "SoftMax", "comb", "sfu")
    # power and clock
    b.wire("csr.ldo_cfg", ["ldo.cfg"], 8, "control")
    b.wire("ldo.vdd_core", ["buf.in"], 1, "status")
    b.wire("buf.out", ["ls.in"], 1, "status")
    b.wire("ls.out", ["dco.en"], 1, "control")
    b.wire("dco.clk", ["ctrl.clk", "acc.clk", "maskb.clk", "datab.clk"], 1, "clock")
    b.wire("csr.cfg", ["vfs.cfg", "mpp.cfg", "eea.cfg"], 16, "control")
    # core
    b.wire("in:axi_s", ["ctrl.axi_s"], 64, "bus")
    b.wire("ctrl.axi_m", ["out:axi_m"], 64, "bus")
    b.wire("ctrl.irq", ["out:irq"], 1, "control")
    b.wire("ctrl.wr", ["msram0.w", "dsram0.w", "msram1.w", "dsram1.w"], 64, "bus")
    for k in (0, 1):
        b.wire(f"msram{k}.q", [f"sdec{k}.mask"], 64)
        b.wire(f"dsram{k}.q", [f"sdec{k}.data"], 256)
        b.wire(f"sdec{k}.y", [f"mux{k}.in0"], 256)
        b.wire(f"ctrl.sel{k}", [f"mux{k}.sel"], 1, "control")
    b.wire("auxbuf.q", ["mux0.in1", "mux1.in1"], 256)
    b.wire("mux0.y", ["fp4.a", "fp8.a"], 256)
    b.wire("mux1.y", ["fp4.b", "fp8.b"], 256)
    b.wire("ctrl.fp_sel", ["fp4.en", "fp8.en"], 1, "control")
    b.wire("fp4.y", ["acc.a"], 256)
    b.wire("fp8.y", ["acc.b"], 256)
    b.wire("acc.y", ["expshift.a"], 256)
    b.wire("expshift.y", ["bias.a"], 256)
    b.wire("bias.y", ["relu.a"], 256)
    b.wire("relu.y", ["trunc.a"], 256)
    b.wire("trunc.y", ["senc.d", "ewadd.a"], 128)
    b.wire("senc.mask", ["maskb.d"], 32)
    b.wire("senc.data", ["datab.d"], 128)
    b.wire("maskb.q", ["muxe.in0"], 128)
    b.wire("datab.q", ["muxe.in1"], 128)
    b.wire("ctrl.enc_sel", ["muxe.sel"], 1, "control")
    b.wire("muxe.y", ["dsram0.wb"], 128, feedback=("dsram0.wb",))
    b.wire("vflut.q", ["vfs.lut"], 32)
    b.wire("amask.q", ["softmax.mask"], 64)
    b.wire("lnparam.q", ["lnorm.p"], 64)
    b.wire("ewadd.y", ["lnorm.a"], 128)
    b.wire("lnorm.y", ["softmax.a"], 128)
    b.wire("softmax.y", ["auxbuf.d"], 128, feedback=("auxbuf.d",))
    b.wire("eea.stop", ["ctrl.stop"], 1, "control", feedback=("ctrl.stop",))
    b.wire("mpp.prec", ["ctrl.prec"], 2, "control", feedback=("ctrl.prec",))
    b.wire("vfs.vf", ["ctrl.vf"], 8, "control", feedback=("ctrl.vf",))
    nodes = {f"b.{n}{k}": {"replicate": {"count": 16, "shape": "stack"}}
             for n in ("msram", "dsram") for k in (0, 1)}
    nodes.update({"b.dec0": {"view_level": "B"}, "b.dec1": {"view_level": "B"},
                  "b.post": {"view_level": "B"}, "b.enc": {"view_level": "B"}})
    expected = {"": "C", "b.core": "C", "b.dec0": "B", "b.dec1": "B", "b.mac": "C",
                "b.post": "B", "b.enc": "B", "b.sfu": "C", "b.ebc": "C"}
    return b.build(), b.hints, _side(expected, nodes)


# ----------------------------------------------------------------------------- Earl Grey
def earlgrey() -> Case:
    """OpenTitan Earl Grey top level, written FROM MEMORY of the public block diagram
    (hw/top_earlgrey/doc). Two crossbars, two power domains, peripherals folded (UART x4,
    I2C x3, SPI host x2, EDN x2). Which IP sits on which crossbar and in which domain is
    approximate. Class D. Replace by a transcription when the figure is available."""
    b = _B()
    b.blk("main", "Main power domain", "group")
    b.blk("aon", "Always-on domain", "group")
    b.blk("ibex", "Ibex core", "cpu", "main")
    b.blk("rvdm", "RV_DM", "controller", "main")
    b.blk("plic", "RV_PLIC", "controller", "main")
    b.blk("xmain", "Main crossbar", "bus", "main")
    b.blk("xperi", "Peri crossbar", "bus", "main")
    main_dev = [("rom", "ROM", "memory"), ("sram", "SRAM", "memory"), ("flash", "eFlash", "memory"),
                ("flashctrl", "Flash ctrl", "controller"), ("kmac", "KMAC", "comb"),
                ("hmac", "HMAC", "comb"), ("aes", "AES", "comb"), ("otbn", "OTBN", "cpu"),
                ("keymgr", "KeyMgr", "comb"), ("csrng", "CSRNG", "comb"), ("edn", "EDN", "comb"),
                ("entropy", "Entropy src", "comb"), ("romctrl", "ROM ctrl", "controller")]
    peri_dev = [("otp", "OTP ctrl", "memory"), ("lcctrl", "LC ctrl", "controller"),
                ("alert", "Alert handler", "controller"), ("spidev", "SPI device", "peripheral"),
                ("spihost", "SPI host", "peripheral"), ("uart", "UART", "peripheral"),
                ("i2c", "I2C", "peripheral"), ("usb", "USB", "peripheral"),
                ("gpio", "GPIO", "peripheral"), ("pattgen", "Pattgen", "peripheral"),
                ("pwm", "PWM", "peripheral"), ("rvtimer", "RV timer", "peripheral")]
    aon_dev = [("aontimer", "AON timer", "peripheral"), ("pinmux", "Pinmux", "comb"),
               ("padctrl", "Padctrl", "comb"), ("sensor", "Sensor ctrl", "controller"),
               ("clkmgr", "Clkmgr", "controller"), ("pwrmgr", "Pwrmgr", "controller"),
               ("rstmgr", "Rstmgr", "controller"), ("sysrst", "SysRST ctrl", "controller"),
               ("adc", "ADC ctrl", "peripheral")]
    for n, lbl, kind in main_dev + peri_dev:
        b.blk(n, lbl, kind, "main")
    for n, lbl, kind in aon_dev:
        b.blk(n, lbl, kind, "aon")
    # hosts
    for h, ports in (("ibex", ("i", "d")), ("rvdm", ("dm",))):
        for p in ports:
            b.wire(f"{h}.{p}_req", [f"xmain.{h}_{p}_req"], 32, "bus")
            b.wire(f"xmain.{h}_{p}_rsp", [f"{h}.{p}_rsp"], 32, "bus", feedback=(f"{h}.{p}_rsp",))
    b.wire("otbn.m_req", ["xmain.otbn_h_req"], 32, "bus")
    b.wire("xmain.otbn_h_rsp", ["otbn.m_rsp"], 32, "bus", feedback=("otbn.m_rsp",))
    # devices on the main crossbar
    for n, _l, _k in main_dev:
        b.wire(f"xmain.{n}_req", [f"{n}.tl_req"], 32, "bus")
        b.wire(f"{n}.tl_rsp", [f"xmain.{n}_rsp"], 32, "bus", feedback=(f"xmain.{n}_rsp",))
    b.wire("xmain.plic_req", ["plic.tl_req"], 32, "bus")
    b.wire("plic.tl_rsp", ["xmain.plic_rsp"], 32, "bus", feedback=("xmain.plic_rsp",))
    b.wire("xmain.peri_req", ["xperi.main_req"], 32, "bus")
    b.wire("xperi.main_rsp", ["xmain.peri_rsp"], 32, "bus", feedback=("xmain.peri_rsp",))
    for n, _l, _k in peri_dev + aon_dev:
        b.wire(f"xperi.{n}_req", [f"{n}.tl_req"], 32, "bus")
        b.wire(f"{n}.tl_rsp", [f"xperi.{n}_rsp"], 32, "bus", feedback=(f"xperi.{n}_rsp",))
    # interrupts, alerts, a few direct links
    for n in ("uart", "gpio", "spidev", "spihost", "i2c", "usb", "hmac", "kmac", "otbn",
              "aontimer", "rvtimer", "flashctrl"):
        b.wire(f"{n}.intr", [f"plic.intr_{n}"], 4, "control", feedback=(f"plic.intr_{n}",))
    b.wire("plic.irq", ["ibex.irq"], 1, "control", feedback=("ibex.irq",))
    for n in ("aes", "kmac", "otp", "lcctrl", "sram", "flashctrl"):
        b.wire(f"{n}.alert", [f"alert.alert_{n}"], 2, "control", feedback=(f"alert.alert_{n}",))
    b.wire("alert.esc", ["pwrmgr.esc"], 4, "control")
    b.wire("romctrl.ctl", ["rom.ctl"], 8, "control")
    b.wire("flashctrl.ctl", ["flash.ctl"], 8, "control")
    b.wire("entropy.ent", ["csrng.ent"], 384)
    b.wire("csrng.rnd", ["edn.rnd"], 128)
    b.wire("edn.edn", ["otbn.edn", "keymgr.edn"], 32)
    b.wire("otp.keys", ["keymgr.keys", "flashctrl.keys"], 256)
    b.wire("lcctrl.lc", ["otp.lc", "keymgr.lc"], 8, "control")
    b.wire("clkmgr.clk", ["ibex.clk", "xmain.clk", "xperi.clk"], 1, "clock")
    b.wire("rstmgr.rst", ["ibex.rst", "xmain.rst", "xperi.rst"], 1, "reset")
    b.wire("pwrmgr.pwr", ["clkmgr.pwr", "rstmgr.pwr"], 4, "control")
    b.wire("in:pads_i", ["padctrl.pads_i"], 48)
    b.wire("padctrl.pads_o", ["out:pads_o"], 48)
    b.wire("padctrl.mio_i", ["pinmux.mio_i"], 48)
    b.wire("pinmux.mio_o", ["padctrl.mio_o"], 48, feedback=("padctrl.mio_o",))
    for n in ("uart", "gpio", "i2c", "spihost"):
        b.wire(f"pinmux.{n}_i", [f"{n}.io_i"], 8)
        b.wire(f"{n}.io_o", [f"pinmux.{n}_o"], 8, feedback=(f"pinmux.{n}_o",))
    nodes = {"b.xmain": {"role": "crossbar"}, "b.xperi": {"role": "crossbar"},
             "b.uart": {"replicate": {"count": 4, "shape": "stack"}},
             "b.i2c": {"replicate": {"count": 3, "shape": "stack"}},
             "b.spihost": {"replicate": {"count": 2, "shape": "stack"}},
             "b.edn": {"replicate": {"count": 2, "shape": "stack"}}}
    # the root holds only the two domains; the bars live inside `main`
    return b.build(), b.hints, _side({"": "C", "b.main": "D", "b.aon": "C"}, nodes)


# ----------------------------------------------------------------------------- arrays, bench
def systolic(rows: int = 4, cols: int = 4) -> Case:
    """rows x cols systolic array: activations flow east, partial sums flow south."""
    b = _B()
    ids = []
    for r in range(rows):
        row = []
        for c in range(cols):
            row.append(b.blk(f"pe{r}{c}", f"PE {r},{c}", "mac"))
        ids.append(row)
    for r in range(rows):
        b.wire(f"in:a{r}", [f"pe{r}0.a"], 8)
        for c in range(cols):
            dst = [f"pe{r}{c + 1}.a"] if c + 1 < cols else [f"out:a_out{r}"]
            b.wire(f"pe{r}{c}.a_out", dst, 8)
    for c in range(cols):
        b.wire(f"in:b{c}", [f"pe0{c}.b"], 8)
        for r in range(rows):
            dst = [f"pe{r + 1}{c}.b"] if r + 1 < rows else [f"out:b_out{c}"]
            b.wire(f"pe{r}{c}.b_out", dst, 16)
    arrays = [{"id": "pe", "shape": [rows, cols], "members": ids, "flow": ["E", "S"]}]
    return b.build(), b.hints, _side({"": "E"}, None, arrays)


def comb_dag60() -> Case:
    d, h = comb_dag(60, seed=3)
    return d, h, _side({"": "A"})


NEW = {
    "fig_system": fig_system, "fig_sfu": fig_sfu, "fig_gs_soc": fig_gs_soc,
    "fig_gs_mac": fig_gs_mac, "fig_gs_edc": fig_gs_edc, "fig_sparse_core": fig_sparse_core,
    "earlgrey": earlgrey, "systolic4x4": systolic, "comb_dag60": comb_dag60,
}

# e0 seeds reused, with the class I expect for each container ("" = root).
E0_SEEDS: dict[str, dict] = {
    "fanin16": _side({"": "A"}),
    "comb_dag20": _side({"": "A"}),
    "comb_dag40": _side({"": "A"}),
    "fanout_3x3": _side({"": "A"}),
    "pipe4": _side({"": "B"}),
    "pipe8_fwd2": _side({"": "B"}),
    "pipe4_hier": _side({"": "B", **{f"b.stage{i}": "B" for i in range(1, 5)}}),
    "uart": _side({"": "B"}),
    "hmac": _side({"": "B", "b.core": "B"}),
    "rv_timer": _side({"": "B"}),
    "fsm_datapath": _side({"": "B"}),
    "wide_block24": _side({"": "B"}),
    "plic": _side({"": "B", "b.proc": "B"}),
    "ibex": _side({"": "C", "b.if": "B", "b.idex": "B", "b.ex": "B", "b.wb": "B"}),
    "deep_hier3": _side({"": "C", "b.h0": "C", "b.h1": "C", "b.h2": "C"}),
    "bus_star8": _side({"": "D"}, {"b.xbar": {"role": "bus"}}),
    "crossbar4x4": _side({"": "E"}, None,
                         [{"id": "xb", "shape": [2, 4], "flow": ["S"],
                           "members": [[f"b.m{i}" for i in range(4)],
                                       [f"b.s{j}" for j in range(4)]]}]),
    "parallel12": _side({"": "B"}),
    "ring6": _side({"": "A"}),
}


def write_all(out: Path = RUNS / "inputs") -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    names = []
    for name, fn in NEW.items():
        d, h, s = fn()
        spec.dump(d, out / f"{name}.diagram.json")
        (out / f"{name}.hints.json").write_text(json.dumps(h, indent=1))
        (out / f"{name}.side.json").write_text(json.dumps(s, indent=1))
        names.append(name)
    for seed, s in E0_SEEDS.items():
        src = E0_INPUTS / "valid" / f"{seed}__base.diagram.json"
        if not src.exists():
            print(f"missing e0 input {src}; run e0/run.py first", file=sys.stderr)
            continue
        shutil.copy(src, out / f"{seed}.diagram.json")
        hp = E0_INPUTS / "hints" / f"{seed}.hints.json"
        h = json.loads(hp.read_text()) if hp.exists() else {"blocks": {}, "sinks": {}}
        (out / f"{seed}.hints.json").write_text(json.dumps(h, indent=1))
        (out / f"{seed}.side.json").write_text(json.dumps(s, indent=1))
        names.append(seed)
    return names


def load(name: str, inp: Path = RUNS / "inputs") -> Case:
    d, issues = spec.load(inp / f"{name}.diagram.json")
    if d is None:
        raise ValueError(f"{name}: {issues[:2]}")
    h = json.loads((inp / f"{name}.hints.json").read_text())
    s = json.loads((inp / f"{name}.side.json").read_text())
    return d, h, s


def main(argv: list[str]) -> int:
    names = write_all()
    bad = 0
    for name in names:
        d, _h, s = load(name)
        issues = spec.validate(d)
        ids = {b.id for b in d.blocks}
        for k in list(s["nodes"]) + [k for k in s["expected"] if k]:
            if k not in ids:
                issues.append(f"sidecar names unknown block {k}")
        for a in s["arrays"]:
            for row in a["members"]:
                for m in row:
                    if m not in ids:
                        issues.append(f"array {a['id']} names unknown block {m}")
        n_c = sum(1 for b in d.blocks if any(x.parent_id == b.id for x in d.blocks))
        print(f"{name:16} {len(d.blocks):3} blocks ({n_c} containers) {len(d.nets):3} nets "
              f"{'ok' if not issues else issues[:2]}")
        bad += bool(issues)
    print(f"{len(names)} inputs, {bad} with issues -> {RUNS / 'inputs'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
