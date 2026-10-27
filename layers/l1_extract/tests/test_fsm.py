"""Deterministic FSM extraction (target "fsm")."""

from pathlib import Path

from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate
from rtl2d_l1.frontend.fsm import _lit_value, _neg, extract_fsms
from rtl2d_l1.pipeline import RunConfig, annotate_design

ROOT = Path(__file__).resolve().parents[1]


def _fsms(files, top=None):
    d = elaborate(files, top=top)
    G = build_graph(d)
    return {f.state: f for f in extract_fsms(d, G, build_entity_tables(G))}


def _edges(f):
    return {(t.src, t.dst, t.cond) for t in f.transitions}


def test_two_process_enum_fsm(corpus):
    f = _fsms(corpus["cache_ctrl"]["files"])["state_q"]
    assert f.style == "two-process" and f.next == "state_d" and f.reset_state == "IDLE"
    assert [s["name"] for s in f.states] == ["IDLE", "LOOKUP", "WRITE_MEM", "REFILL", "RESPOND"]
    assert _edges(f) == {
        ("IDLE", "LOOKUP", "cpu_req_valid"),
        ("LOOKUP", "WRITE_MEM", "we_q"),
        ("LOOKUP", "RESPOND", "!we_q && hit"),
        ("LOOKUP", "REFILL", "!we_q && !hit"),
        ("WRITE_MEM", "RESPOND", "mem_ack"),
        ("REFILL", "RESPOND", "mem_ack"),
        ("RESPOND", "IDLE", "1"),
    }  # the unreachable `default:` adds nothing
    outs = {o["signal"]: o["kind"] for o in f.outputs}
    assert outs["cpu_req_ready"] == "moore" and outs["stall_o"] == "moore"


def test_one_process_localparam_fsm(corpus):
    f = _fsms(corpus["ugly_mul"]["files"])["m"]
    assert f.style == "one-process" and f.reset_state == "I"
    assert _edges(f) == {("I", "R", "s"), ("R", "F", "z"), ("F", "I", "1")}


def test_ternary_next_state_and_trailing_reset():
    v = ROOT / "data/corpus/verilog-eval/dataset_spec-to-rtl/Prob140_fsm_hdlc_ref.sv"
    if not v.exists():
        return  # dataset not downloaded
    f = _fsms([v], "RefModule")["state"]
    assert f.reset_state == "S0"
    assert ("S5", "SDISC", "!in") in _edges(f) and ("S6", "SERR", "in") in _edges(f)
    assert "'x" not in {s["name"] for s in f.states}


def test_parameter_disabled_logic_is_pruned():
    v = ROOT / "data/corpus/picorv32/picorv32.v"
    if not v.exists():
        return
    f = _fsms([v], "picorv32")["cpu_state"]
    assert f.reset_state == "cpu_state_fetch"
    conds = " ".join(t.cond for t in f.transitions)
    assert "ENABLE_IRQ" not in conds and "WITH_PCPI" not in conds  # constant-folded away
    assert ("cpu_state_fetch", "cpu_state_ld_rs1", "decoder_trigger && !instr_jal") in _edges(f)


def test_helpers():
    assert _lit_value("2'b0") == _lit_value("2'b00") == "0"
    assert _lit_value("8'hFF") == "255"
    assert _neg("!ground") == "ground" and _neg("in") == "!in" and _neg("(a || b)") == "!(a || b)"


def test_target_fsm_writes_outputs(tmp_path, corpus):
    d = corpus["uart_tx"]
    run = annotate_design(
        d["files"],
        top=d["top"],
        cfg=RunConfig(mode="heuristic", targets=frozenset({"block", "fsm", "timing"})),
        out_dir=tmp_path,
    )
    assert [f.state for f in run.fsms] == ["state_q"]
    out = tmp_path / "uart_tx"
    assert (out / "fsm.json").exists() and (out / "fsm" / "uart_tx.state_q.mmd").exists()
    assert (out / "timing.json").exists() and (out / "anchors.json").exists()
    mmd = (out / "fsm" / "uart_tx.state_q.mmd").read_text(encoding="utf-8")
    assert "[*] --> S_IDLE" in mmd and "S_DATA --> S_STOP : baud_tick && bit_idx_q == 3'd7" in mmd
    # block-only run produces no fsm files
    run2 = annotate_design(
        d["files"], top=d["top"], cfg=RunConfig(mode="heuristic"), out_dir=tmp_path / "b"
    )
    assert not run2.fsms and not (tmp_path / "b" / "uart_tx" / "fsm.json").exists()
