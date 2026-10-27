"""Synthetic valid/ready pipeline generator.

`pipeline(4)` is the pipe4 circuit described in rtl_block_diagram_design_space.md:
10 blocks, 48 ports (8 on the boundary), 18 nets.
"""

from __future__ import annotations

from spec import SCHEMA_VERSION, Block, Diagram, Net, Port


class _Builder:
    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.ports: list[Port] = []
        self.nets: list[Net] = []

    def block(self, id: str, label: str, kind: str, parent: str | None = None) -> str:
        self.blocks.append(Block(id=id, label=label, kind=kind, parent_id=parent))
        return id

    def port(self, owner: str | None, name: str, direction: str, width: int, cls: str) -> str:
        pid = f"{owner}.{name}" if owner else f"p.{name}"
        self.ports.append(
            Port(id=pid, owner_block_id=owner, direction=direction, width=width, class_=cls)
        )
        return pid

    def net(self, name: str, source: str, targets: list[str], width: int, cls: str) -> None:
        self.nets.append(
            Net(id=f"n.{name}", source=source, targets=targets, width=width, class_=cls)
        )

    def build(self) -> Diagram:
        return Diagram(
            schema_version=SCHEMA_VERSION, blocks=self.blocks, ports=self.ports, nets=self.nets
        )


def pipeline(
    stages: int = 4,
    width: int = 32,
    forwards: int = 1,
    controller: bool = True,
    hier: bool = False,
) -> Diagram:
    """N-stage pipeline: S1 -> P1 -> ... -> SN -> PN.

    forwards: number of forwarding muxes. Mux k sits in front of the last-k stage and
      takes that stage's own register output as feedback (pipe4: one mux before S3 fed by P3).
    controller: add Pipe Ctrl driving `en` and the mux selects; without it registers have
      no enable and no mux is generated.
    hier: wrap each (S_i, P_i) pair in a parent "stage" block.
    """
    if stages < 1:
        raise ValueError("stages must be >= 1")
    b = _Builder()
    fwd_stages = list(range(stages - 1, 1, -1))[:forwards] if controller else []

    clk = b.port(None, "clk", "input", 1, "clock")
    rst = b.port(None, "rst_n", "input", 1, "reset")
    cur = b.port(None, "in_data", "input", width, "data")
    cur_name = "in_data"
    clk_sinks: list[str] = []
    rst_sinks: list[str] = []
    en_sinks: list[str] = []
    sel_sinks: dict[int, str] = {}
    fb_sinks: dict[int, str] = {}

    for i in range(1, stages + 1):
        parent = b.block(f"b.stage{i}", f"Stage {i}", "stage") if hier else None
        if i in fwd_stages:
            m = b.block(f"b.fwd{i}", "FWD MUX", "mux", parent)
            b.net(cur_name, cur, [b.port(m, "a", "input", width, "data")], width, "data")
            fb_sinks[i] = b.port(m, "b", "input", width, "data")
            sel_sinks[i] = b.port(m, "sel", "input", 1, "control")
            cur, cur_name = b.port(m, "y", "output", width, "data"), f"fwd{i}_y"
        s = b.block(f"b.s{i}", f"S{i}", "comb", parent)
        b.net(cur_name, cur, [b.port(s, "a", "input", width, "data")], width, "data")
        cur, cur_name = b.port(s, "y", "output", width, "data"), f"s{i}_y"

        p = b.block(f"b.p{i}", f"P{i}", "register", parent)
        b.net(cur_name, cur, [b.port(p, "d", "input", width, "data")], width, "data")
        cur, cur_name = b.port(p, "q", "output", width, "data"), f"p{i}_q"
        if controller:
            en_sinks.append(b.port(p, "en", "input", 1, "control"))
        clk_sinks.append(b.port(p, "clk", "input", 1, "clock"))
        rst_sinks.append(b.port(p, "rst_n", "input", 1, "reset"))

    b.net(cur_name, cur, [b.port(None, "out_data", "output", width, "data")], width, "data")

    if controller:
        c = b.block("b.ctrl", "Pipe Ctrl", "controller")
        clk_sinks.append(b.port(c, "clk", "input", 1, "clock"))
        rst_sinks.append(b.port(c, "rst_n", "input", 1, "reset"))
        b.net(
            "in_valid",
            b.port(None, "in_valid", "input", 1, "control"),
            [b.port(c, "in_valid", "input", 1, "control")],
            1,
            "control",
        )
        b.net(
            "out_ready",
            b.port(None, "out_ready", "input", 1, "control"),
            [b.port(c, "out_ready", "input", 1, "control")],
            1,
            "control",
        )
        b.net(
            "in_ready",
            b.port(c, "in_ready", "output", 1, "control"),
            [b.port(None, "in_ready", "output", 1, "control")],
            1,
            "control",
        )
        b.net(
            "out_valid",
            b.port(c, "out_valid", "output", 1, "control"),
            [b.port(None, "out_valid", "output", 1, "control")],
            1,
            "control",
        )
        b.net("en", b.port(c, "en", "output", 1, "control"), en_sinks, 1, "control")
        for i, sink in sel_sinks.items():
            name = "fwd_sel" if len(sel_sinks) == 1 else f"fwd{i}_sel"
            b.net(name, b.port(c, name, "output", 1, "control"), [sink], 1, "control")

    b.net("clk", clk, clk_sinks, 1, "clock")
    b.net("rst_n", rst, rst_sinks, 1, "reset")

    d = b.build()
    # Attach each feedback sink to the net driven by that stage's register output.
    for i, sink in fb_sinks.items():
        next(n for n in d.nets if n.source == f"b.p{i}.q").targets.append(sink)
    return d


def pipeline_hints(d: Diagram) -> dict[str, dict[str, dict[str, object]]]:
    """Layout hints for a `pipeline()` diagram, read off its block IDs.

    Experiment-local format (no contract yet); field names from the design-space
    document, S3. Stage i holds S_i and its forwarding mux; P_i sits on boundary i.
    """
    blocks: dict[str, dict[str, object]] = {}
    for b in d.blocks:
        name = b.id.removeprefix("b.")
        if name == "ctrl":
            blocks[b.id] = {"lane": "control"}
        elif name[0] == "p" and name[1:].isdigit():
            blocks[b.id] = {"stage_boundary": int(name[1:])}
        elif name[0] == "s" and name[1:].isdigit():
            blocks[b.id] = {"stage_index": int(name[1:])}
        elif name.startswith("fwd"):
            blocks[b.id] = {"stage_index": int(name[3:])}
    sinks = {
        f"{n.id}|{t}": {"flow_role": "feedback"}
        for n in d.nets
        for t in n.targets
        if ".fwd" in t and t.endswith(".b")
    }
    return {"blocks": blocks, "sinks": sinks}
