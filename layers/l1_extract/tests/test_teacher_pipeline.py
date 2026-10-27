"""Teacher path with a fake Anthropic client: retry, refine, Run Store reuse, SFT export."""

import json

from rtl2d_l1.distill.export import export_sft
from rtl2d_l1.llm.teacher import Teacher, TeacherConfig
from rtl2d_l1.pipeline import RunConfig, annotate_design
from rtl2d_l1.schema import annotation_json_schema
from rtl2d_l1.store import RunStore


def _ann(anchors, summary="test"):
    return {"module_summary": summary, "anchors": anchors, "groups": [], "interfaces": []}


def _anc(i, n, role, imp="critical", trace="control_backward"):
    return {"id": i, "name": n, "role": role, "importance": imp, "trace": trace, "why": "x"}


def test_retry_refine_store_reuse_and_export(tmp_path, corpus, built, fake_client_cls):
    turns = {"n": 0}
    ids = {r.name: r.id for r in built["uart_tx"][2]["uart_tx"].rows}

    def responder(params):
        turns["n"] += 1
        msgs = params["messages"]
        assert params["output_config"]["format"]["schema"] == annotation_json_schema()
        assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
        last = msgs[-1]["content"]
        if len(msgs) == 1:  # first turn: hallucinated id -> must trigger a retry
            return _ann([_anc("E77", "ghost", "FSM_STATE")])
        if "failed validation" in last:  # retry: valid, but misses the FSM -> refine round
            return _ann([_anc(ids["tx_valid"], "tx_valid", "HANDSHAKE_VALID", trace="interface")])
        if "Automatic checks" in last:
            assert "state_q" in last
            return _ann(
                [
                    _anc(ids["tx_valid"], "tx_valid", "HANDSHAKE_VALID", trace="interface"),
                    _anc(ids["state_q"], "state_q", "FSM_STATE"),
                ]
            )
        raise AssertionError(last[:200])

    client = fake_client_cls(responder)
    store = RunStore(tmp_path / "runs")
    cfg = RunConfig(mode="teacher", teacher=TeacherConfig())
    d = corpus["uart_tx"]
    run = annotate_design(
        d["files"],
        top=d["top"],
        cfg=cfg,
        store=store,
        teacher=Teacher(cfg.teacher, client=client),
        out_dir=tmp_path / "out",
    )
    res = run.results["uart_tx"]
    assert res.source == "teacher"
    assert {a.name for a in res.anchors} == {"tx_valid", "state_q"}
    assert turns["n"] == 3
    # thinking blocks were echoed back unchanged in the continued conversation
    last_call = client.calls[-1]["messages"]
    assert last_call[1]["role"] == "assistant" and last_call[1]["content"][0]["type"] == "thinking"
    assert (tmp_path / "out" / "uart_tx" / "anchors.json").exists()
    assert store.spent_usd() > 0

    # second run: everything comes from the Run Store, zero API calls
    client2 = fake_client_cls(lambda p: (_ for _ in ()).throw(AssertionError("API called")))
    run2 = annotate_design(
        d["files"], top=d["top"], cfg=cfg, store=store, teacher=Teacher(cfg.teacher, client=client2)
    )
    assert {a.name for a in run2.results["uart_tx"].anchors} == {"tx_valid", "state_q"}
    assert not client2.calls

    out = export_sft(store, tmp_path / "sft.jsonl")
    assert out["written"] == 1
    sample = json.loads((tmp_path / "sft.jsonl").read_text(encoding="utf-8").splitlines()[0])
    final = json.loads(sample["messages"][2]["content"])
    assert {a["name"] for a in final["anchors"]} == {"tx_valid", "state_q"}


def test_plan_mode_waves(tmp_path, corpus):
    store = RunStore(tmp_path / "runs")
    d = corpus["soc_top"]
    run = annotate_design(d["files"], top=d["top"], cfg=RunConfig(mode="plan"), store=store)
    planned = {p["module"] for p in run.plan}
    # leaves first; the top waits for its children
    assert planned == {"sync_fifo", "rr_arbiter", "uart_tx"}
    assert any("waiting for children" in ln for ln in run.log)
