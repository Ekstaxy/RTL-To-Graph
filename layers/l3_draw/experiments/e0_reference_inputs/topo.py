"""Synthetic shapes other than pipelines, and edge cases the format allows.

`SHAPES` are structures L3 will meet in real designs (trees, buses, loops, hierarchy).
`EDGE` are small inputs that pass validation but are unusual; L3 must not crash on them.
Every function returns (Diagram, hints); hints are empty where stages make no sense.
"""

from __future__ import annotations

import random

from real import _B, Hints
from spec import Diagram

Case = tuple[Diagram, Hints]


def chain(n: int = 12) -> Case:
    """n combinational blocks in series: the longest possible single trunk."""
    b = _B()
    prev = "in:a"
    for i in range(n):
        b.blk(f"c{i}", f"C{i}", "comb", stage_index=i)
        b.wire(prev, [f"c{i}.a"], 16, name=f"w{i}")
        prev = f"c{i}.y"
    b.wire(prev, ["out:y"], 16, name="y")
    return b.build(), b.hints


def fanout_tree(depth: int = 3, k: int = 3) -> Case:
    """One source fanning out k-ways per level (decoder / clock-tree shape)."""
    b = _B()
    b.blk("n", "root", "comb")
    b.wire("in:a", ["n.a"], 8)
    level = ["n"]
    for _ in range(depth):
        nxt = []
        for name in level:
            kids = [f"{name}{j}" for j in range(k)]
            for kid in kids:
                b.blk(kid, kid, "comb")
            b.wire(f"{name}.y", [f"{kid}.a" for kid in kids], 8)
            nxt += kids
        level = nxt
    for name in level:
        b.wire(f"{name}.y", [f"out:{name}"], 8)
    return b.build(), b.hints


def fanin_tree(leaves: int = 16) -> Case:
    """Binary reduction tree (adder tree): many inputs, one output."""
    b = _B()
    level = [f"in:x{i}" for i in range(leaves)]
    depth = 0
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            name = f"a{depth}_{i // 2}"
            b.blk(name, "+", "adder", stage_index=depth)
            b.wire(level[i], [f"{name}.a"], 8, name=f"{name}_a")
            b.wire(level[i + 1], [f"{name}.b"], 8, name=f"{name}_b")
            nxt.append(f"{name}.y")
        level, depth = nxt, depth + 1
    b.wire(level[0], ["out:sum"], 8, name="sum")
    return b.build(), b.hints


def comb_dag(n: int = 20, seed: int = 1) -> Case:
    """Random combinational DAG: no stages, arbitrary fan-in/fan-out, long skip edges."""
    rng = random.Random(seed)
    b = _B()
    outs = ["in:a", "in:b", "in:c"]
    sinks: dict[str, list[str]] = {o: [] for o in outs}
    for i in range(n):
        b.blk(f"g{i}", f"G{i}", "comb")
        for j, src in enumerate(rng.sample(outs, k=min(len(outs), rng.choice([1, 2, 2, 3])))):
            sinks[src].append(f"g{i}.i{j}")
        outs.append(f"g{i}.y")
        sinks[f"g{i}.y"] = []
    for src, dst in sinks.items():
        if not dst and not src.startswith("in:"):
            dst = [f"out:{src.split('.')[0]}"]
        if dst:
            b.wire(src, dst, 8)
    return b.build(), b.hints


def bus_star(n: int = 8) -> Case:
    """One host, one interconnect, n peripherals; request and response per peripheral."""
    b = _B()
    b.blk("host", "Host", "cpu")
    b.blk("xbar", "Interconnect", "bus")
    b.wire("host.req", ["xbar.h_req"], 109, "bus")
    b.wire("xbar.h_rsp", ["host.rsp"], 66, "bus", feedback=("host.rsp",))
    for i in range(n):
        b.blk(f"dev{i}", f"Peripheral {i}", "peripheral")
        b.wire(f"xbar.req{i}", [f"dev{i}.req"], 109, "bus")
        b.wire(f"dev{i}.rsp", [f"xbar.rsp{i}"], 66, "bus", feedback=(f"xbar.rsp{i}",))
        b.wire(f"dev{i}.intr", [f"host.intr{i}"], 1, "control", feedback=(f"host.intr{i}",))
    return b.build(), b.hints


def crossbar(m: int = 4, n: int = 4) -> Case:
    """Every master wired to every slave: the crossings cannot all be removed."""
    b = _B()
    for i in range(m):
        b.blk(f"m{i}", f"M{i}", "comb")
        b.wire(f"in:a{i}", [f"m{i}.a"], 8)
    for j in range(n):
        b.blk(f"s{j}", f"S{j}", "comb")
        b.wire(f"s{j}.y", [f"out:y{j}"], 8)
    for i in range(m):
        b.wire(f"m{i}.y", [f"s{j}.i{i}" for j in range(n)], 8)
    return b.build(), b.hints


def ring(n: int = 6) -> Case:
    """Registers in a loop with no boundary data input: every layering has a back edge."""
    b = _B()
    for i in range(n):
        b.blk(f"r{i}", f"R{i}", "register", stage_boundary=i)
    for i in range(n):
        j = (i + 1) % n
        b.wire(f"r{i}.q", [f"r{j}.d"], 8, feedback=(f"r{j}.d",) if j == 0 else ())
    b.wire("in:clk", [f"r{i}.clk" for i in range(n)], 1, "clock")
    return b.build(), b.hints


def fsm_datapath() -> Case:
    """Controller and datapath: control goes down, status comes back up."""
    b = _B()
    b.blk("fsm", "FSM", "controller", lane="control")
    for i, name in enumerate(["load", "shift", "acc", "cmp"]):
        b.blk(name, name.upper(), "register" if name == "acc" else "comb", stage_index=i + 1)
    b.wire("in:start", ["fsm.start"], 1, "control")
    b.wire("in:d", ["load.d"], 16)
    b.wire("load.y", ["shift.d"], 16)
    b.wire("shift.y", ["acc.d"], 16)
    b.wire("acc.q", ["cmp.a", "shift.fb"], 16, name="acc", feedback=("shift.fb",))
    b.wire("cmp.y", ["out:result"], 16)
    b.wire("fsm.load_en", ["load.en"], 1, "control")
    b.wire("fsm.shift_en", ["shift.en"], 1, "control")
    b.wire("fsm.acc_en", ["acc.en"], 1, "control")
    b.wire("cmp.zero", ["fsm.zero"], 1, "status", feedback=("fsm.zero",))
    b.wire("fsm.done", ["out:done"], 1, "control")
    return b.build(), b.hints


def dual_pipe() -> Case:
    """Two 3-stage pipelines side by side with a cross link at each stage."""
    b = _B()
    for ch in "ab":
        prev = f"in:{ch}_in"
        for i in range(1, 4):
            b.blk(f"{ch}s{i}", f"{ch.upper()}{i}", "comb", stage_index=i)
            b.blk(f"{ch}p{i}", f"{ch.upper()}P{i}", "register", stage_boundary=i)
            b.wire(prev, [f"{ch}s{i}.a"], 32, name=f"{ch}{i}_a")
            b.wire(f"{ch}s{i}.y", [f"{ch}p{i}.d"], 32)
            prev = f"{ch}p{i}.q"
        b.wire(prev, [f"out:{ch}_out"], 32, name=f"{ch}_out")
    for i in range(1, 3):
        b.wire(f"as{i}.xo", [f"bs{i + 1}.xi"], 8, name=f"ab{i}")
        b.wire(f"bs{i}.xo", [f"as{i + 1}.xi"], 8, name=f"ba{i}")
    return b.build(), b.hints


def deep_hier(levels: int = 3) -> Case:
    """Containers nested `levels` deep, two leaf chains, nets crossing container borders."""
    b = _B()
    parent = None
    for lv in range(levels):
        b.blk(f"h{lv}", f"Level {lv}", "group", parent)
        b.blk(f"x{lv}", f"X{lv}", "comb", f"h{lv}")
        parent = f"h{lv}"
    b.blk("y", "Y", "comb", parent)
    b.blk("top", "Outside", "comb")
    b.wire("in:a", ["x0.a"], 8)
    for lv in range(levels - 1):
        b.wire(f"x{lv}.y", [f"x{lv + 1}.a"], 8)
    b.wire(f"x{levels - 1}.y", ["y.a"], 8)
    b.wire("y.y", ["top.a", "x0.fb"], 8, feedback=("x0.fb",))
    b.wire("top.y", ["out:y"], 8)
    return b.build(), b.hints


def wide_block(n: int = 24) -> Case:
    """One block with n outputs, each to its own small block (register file / CSR shape)."""
    b = _B()
    b.blk("reg", "CSR", "regfile")
    b.wire("in:bus", ["reg.bus"], 32, "bus")
    for i in range(n):
        b.blk(f"u{i}", f"U{i}", "comb")
        b.wire(f"reg.q{i}", [f"u{i}.cfg"], 1 + i % 8, "control")
    return b.build(), b.hints


def parallel_nets(n: int = 12) -> Case:
    """n separate nets between the same two blocks: what a missing bundle looks like."""
    b = _B()
    b.blk("a", "Source", "comb")
    b.blk("z", "Sink", "comb")
    for i in range(n):
        b.wire(f"a.o{i}", [f"z.i{i}"], 1, "control" if i % 3 == 0 else "data")
    return b.build(), b.hints


def big_fanout(n: int = 24) -> Case:
    """One control net with n sinks, each sink also on a data chain."""
    b = _B()
    b.blk("ctl", "Enable Gen", "controller", lane="control")
    prev = "in:d"
    for i in range(n):
        b.blk(f"r{i}", f"R{i}", "register", stage_boundary=i)
        b.wire(prev, [f"r{i}.d"], 8, name=f"d{i}")
        prev = f"r{i}.q"
    b.wire(prev, ["out:q"], 8, name="q")
    b.wire("ctl.en", [f"r{i}.en" for i in range(n)], 1, "control")
    return b.build(), b.hints


# --- edge cases: valid by the ADR-0002 rules, unusual to draw ---


def empty() -> Case:
    return _B().build(), {"blocks": {}, "sinks": {}}


def single_block() -> Case:
    b = _B()
    b.blk("only", "Only", "comb")
    return b.build(), b.hints


def boundary_only() -> Case:
    """No blocks; one net straight from a boundary input to a boundary output."""
    b = _B()
    b.wire("in:a", ["out:y"], 8)
    b.port(None, "unused", "input", 1, "control")
    return b.build(), b.hints


def isolated() -> Case:
    """Blocks with no nets at all and ports that nothing connects to."""
    b = _B()
    for i in range(3):
        b.blk(f"i{i}", f"Island {i}", "comb")
        b.port(f"b.i{i}", "a", "input", 4, "data")
        b.port(f"b.i{i}", "y", "output", 4, "data")
    return b.build(), b.hints


def passthrough() -> Case:
    """A boundary input that feeds a block and also leaves the design unchanged."""
    b = _B()
    b.blk("u", "U", "comb")
    b.wire("in:a", ["u.a", "out:a_copy"], 8)
    b.wire("u.y", ["out:y"], 8)
    return b.build(), b.hints


def self_loop() -> Case:
    """A block whose output feeds its own input (an accumulator drawn as one box)."""
    b = _B()
    b.blk("acc", "Accumulator", "register")
    b.wire("in:d", ["acc.d"], 8)
    b.wire("acc.q", ["acc.fb", "out:q"], 8, feedback=("acc.fb",))
    return b.build(), b.hints


def hier_ports() -> Case:
    """A container that has its own ports as well as children.

    ADR-0002 rule 4 does not let a container input drive a net, so a signal cannot pass
    "through" the container port; the port and the child are two unrelated endpoints.
    """
    b = _B()
    b.blk("outer", "Outer", "group")
    b.blk("inner", "Inner", "comb", "outer")
    b.blk("src", "Src", "comb")
    b.wire("src.y", ["outer.a", "inner.a"], 8)
    b.wire("inner.y", ["out:y"], 8)
    b.wire("outer.status", ["out:status"], 1, "status")
    return b.build(), b.hints


def widths() -> Case:
    """Widths 1, 2 and 4096 side by side."""
    b = _B()
    b.blk("u", "U", "comb")
    b.blk("v", "V", "comb")
    for name, w in [("bit", 1), ("pair", 2), ("huge", 4096)]:
        b.wire(f"in:{name}", [f"u.{name}"], w)
        b.wire(f"u.{name}_o", [f"v.{name}"], w)
        b.wire(f"v.{name}_o", [f"out:{name}_o"], w)
    return b.build(), b.hints


def labels() -> Case:
    """Empty, very long, multi-word, non-ASCII and markup-like labels."""
    b = _B()
    texts = ["", "x", "a very long label that keeps going for quite a while indeed",
             "暫存器堆", "<b>&amp;</b>", "two\nlines"]
    prev = "in:a"
    for i, text in enumerate(texts):
        b.blk(f"l{i}", text, "comb")
        b.wire(prev, [f"l{i}.a"], 8, name=f"w{i}")
        prev = f"l{i}.y"
    b.wire(prev, ["out:y"], 8, name="y")
    return b.build(), b.hints


def unknown_kinds() -> Case:
    """Kinds and classes outside any vocabulary L3 could know."""
    b = _B()
    for i, kind in enumerate(["quantum_gate", "", "MUX", "Register", "???"]):
        b.blk(f"k{i}", f"K{i}", kind)
    b.wire("in:a", ["k0.a"], 8, "mystery")
    for i in range(4):
        b.wire(f"k{i}.y", [f"k{i + 1}.a"], 8, ["", "DATA", "Clock", "tri-state"][i])
    b.wire("k4.y", ["out:y"], 8, "data")
    return b.build(), b.hints


SHAPES = {
    "chain12": chain,
    "fanout_3x3": fanout_tree,
    "fanin16": fanin_tree,
    "comb_dag20": comb_dag,
    "comb_dag40": lambda: comb_dag(40, seed=2),
    "bus_star8": bus_star,
    "crossbar4x4": crossbar,
    "ring6": ring,
    "fsm_datapath": fsm_datapath,
    "dual_pipe": dual_pipe,
    "deep_hier3": deep_hier,
    "wide_block24": wide_block,
    "parallel12": parallel_nets,
    "fanout24": big_fanout,
}

EDGE = {
    "edge_empty": empty,
    "edge_single": single_block,
    "edge_boundary_only": boundary_only,
    "edge_isolated": isolated,
    "edge_passthrough": passthrough,
    "edge_self_loop": self_loop,
    "edge_hier_ports": hier_ports,
    "edge_widths": widths,
    "edge_labels": labels,
    "edge_unknown_kinds": unknown_kinds,
}
