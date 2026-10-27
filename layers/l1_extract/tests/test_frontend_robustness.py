from pathlib import Path

from pyslang import ast

from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate

DATA = Path(__file__).resolve().parent / "data"


def _table(name, top):
    d = elaborate([DATA / name], top=top)
    G = build_graph(d)
    return d, G, {r.name: r for r in build_entity_tables(G)[0].rows}


def test_dead_illegal_branch_does_not_drop_the_block():
    """slang turns the whole always block into an InvalidStatement (with no diagnostic) when a
    branch that is dead under the current parameters is illegal; dataflow must survive."""
    d, G, rows = _table("dead_branch.v", "dead_branch")
    kinds = [
        type(m.body).__name__ for m in d.tops[0].body if isinstance(m, ast.ProceduralBlockSymbol)
    ]
    assert "InvalidStatement" in kinds and not d.errors  # the slang behaviour this guards against
    assert any("syntax-fallback" in u for u in G.unsupported)
    assert rows["st_next"].fanin >= 1 and rows["st_reg"].fanout >= 1
    assert rows["go"].fanout >= 1 and rows["d"].fanout >= 1
    assert rows["st_reg"].fsm_candidate


def test_false_sync_resets_are_demoted():
    _, _, rows = _table("false_resets.v", "false_resets")
    assert rows["i_reset"].auto_role == "RESET"
    assert rows["i_valid"].auto_role is None  # also used as data: a valid, not a reset
    assert rows["reset_crc"].auto_role is None  # driven by FSM logic: a datapath clear


def test_reset_status_does_not_leak_through_expressions():
    d = elaborate([DATA / "false_resets.v"], top="false_resets2")
    G = build_graph(d)
    tables = {t.module: t for t in build_entity_tables(G)}
    rows = {r.name: r for r in tables["false_resets2"].rows}
    assert rows["i_reset"].auto_role == "RESET"
    assert rows["i_valid"].auto_role is None  # only part of `.rst(i_reset || !i_valid)`
    assert rows["i_stall"].auto_role is None  # only part of `if (i_reset || !i_stall)`
    assert {r.name: r for r in tables["fr_child"].rows}["rst"].auto_role == "RESET"
