import json
from pathlib import Path

from rtl2d_l1.frontend import EdgeType
from rtl2d_l1.frontend.entities import canonical_instances

ROOT = Path(__file__).resolve().parents[1]


def _edge(G, s, t, et):
    return any(d["type"] == et for d in G.g.get_edge_data(s, t, default={}).values())


def test_fifo_edges(built):
    _, G, _ = built["sync_fifo"]
    p = "sync_fifo."
    assert _edge(G, p + "wptr_q", p + "mem_q", EdgeType.ADDR)
    assert _edge(G, p + "in_data", p + "mem_q", EdgeType.DATA)
    assert _edge(G, p + "do_push", p + "mem_q", EdgeType.CONTROL)
    assert _edge(G, p + "rst_n", p + "count_q", EdgeType.RESET)
    assert _edge(G, p + "clk", p + "count_q", EdgeType.CLOCK)
    assert _edge(G, p + "rptr_q", p + "out_data", EdgeType.ADDR)
    # reset is not double-counted as control
    assert not _edge(G, p + "rst_n", p + "count_q", EdgeType.CONTROL)
    assert G.nodes[p + "count_q"].is_state and not G.nodes[p + "do_push"].is_state


def test_conditional_operator_is_control(built):
    _, G, _ = built["ugly_mul"]
    assert _edge(G, "ugly_mul.y", "ugly_mul.t", EdgeType.CONTROL)  # t = y[0] ? acc + x : acc
    assert _edge(G, "ugly_mul.acc", "ugly_mul.t", EdgeType.DATA)


def test_hierarchy_ports(built):
    _, G, tables = built["soc_top"]
    assert len(G.instances) == 7  # top + 4 fifos + arbiter + uart
    assert _edge(G, "soc_top.u_uart.tx_ready", "soc_top.tx_ready", EdgeType.PORT)
    assert _edge(G, "soc_top.tx_byte", "soc_top.u_uart.tx_data", EdgeType.PORT)
    order = [m for m, _ in canonical_instances(G)]
    assert order[-1] == "soc_top" and set(order) == {
        "soc_top",
        "sync_fifo",
        "rr_arbiter",
        "uart_tx",
    }
    top = tables["soc_top"]
    insts = [r for r in top.rows if r.kind == "inst"]
    assert [r.name for r in insts] == ["gen_ch[*].u_fifo", "u_arb", "u_uart"]
    assert top.by_name()["clk"].auto_role == "CLOCK"  # propagated through child ports


def test_fsm_candidates(built):
    found = {
        (m, r.name)
        for _, (_, _, ts) in built.items()
        for m, t in ts.items()
        for r in t.rows
        if r.fsm_candidate
    }
    assert found == {("uart_tx", "state_q"), ("cache_ctrl", "state_q"), ("ugly_mul", "m")}


def test_entity_ids_follow_declaration_order(built):
    for _, (_, _, ts) in built.items():
        for t in ts.values():
            sig = [r for r in t.rows if r.kind != "inst"]
            assert [r.id for r in sig] == [f"E{i}" for i in range(1, len(sig) + 1)]
            lines = [r.line for r in sig]
            assert lines == sorted(lines)


def test_gold_ids_match_tables(built):
    tables = {m: t for _, (_, _, ts) in built.items() for m, t in ts.items()}
    for p in (ROOT / "gold").glob("*.json"):
        g = json.loads(p.read_text(encoding="utf-8"))
        rows = tables[g["module"]].by_id()
        for a in g["anchors"]:
            assert rows[a["id"]].name == a["name"], (p.name, a)
            for alt in a["alt_ids"]:
                assert alt in rows, (p.name, alt)
