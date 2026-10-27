"""Multi-pass self-audit protocol and the evidence-line validator."""

from rtl2d_l1.llm.teacher import Teacher, TeacherConfig
from rtl2d_l1.pipeline import RunConfig, annotate_design
from rtl2d_l1.schema import Anchor, ModuleAnnotation
from rtl2d_l1.store import RunStore
from rtl2d_l1.taxonomy import Importance, Role, TraceHint
from rtl2d_l1.validate import check_evidence


def _line_of(table, name):
    src = table.source_text(numbered=False).splitlines()
    for i, ln in enumerate(src, start=table.line_start):
        if name in ln and ("<=" in ln or "assign" in ln):
            return i
    return table.by_name()[name].line


def test_evidence_validator(built):
    t = built["uart_tx"][2]["uart_tx"]
    ids = {r.name: r.id for r in t.rows}
    good = Anchor(
        id=ids["state_q"],
        name="state_q",
        role=Role.FSM_STATE,
        importance=Importance.critical,
        trace=TraceHint.control_backward,
        lines=[_line_of(t, "state_q")],
    )
    wrong_line = good.model_copy(
        update={"lines": [t.line_start]}
    )  # module header does not mention state_q
    outside = good.model_copy(update={"lines": [t.line_end + 50]})
    none = good.model_copy(update={"lines": []})
    assert check_evidence(ModuleAnnotation(anchors=[good]), t) == []
    assert "not mentioned" in check_evidence(ModuleAnnotation(anchors=[wrong_line]), t)[0]
    assert "outside the module" in check_evidence(ModuleAnnotation(anchors=[outside]), t)[0]
    assert "cites no RTL lines" in check_evidence(ModuleAnnotation(anchors=[none]), t)[0]


def test_multipass_converges_and_stores_rounds(tmp_path, corpus, built, fake_client_cls):
    t = built["uart_tx"][2]["uart_tx"]
    ids = {r.name: r.id for r in t.rows}

    def anc(name, role, imp="critical"):
        return {
            "id": ids[name],
            "name": name,
            "role": role,
            "importance": imp,
            "trace": "control_backward",
            "why": "x",
            "lines": [_line_of(t, name)],
        }

    v1 = {
        "module_summary": "s",
        "anchors": [anc("tx_valid", "HANDSHAKE_VALID")],
        "groups": [],
        "interfaces": [],
    }
    v2 = dict(v1, anchors=v1["anchors"] + [anc("state_q", "FSM_STATE")])
    seen = []

    def responder(params):
        last = params["messages"][-1]["content"]
        seen.append(last[:12])
        if len(params["messages"]) == 1:
            return v1
        assert last.startswith("AUDIT PASS")
        return v2  # pass 2 adds the FSM, pass 3 returns it unchanged -> converged

    store = RunStore(tmp_path / "runs")
    cfg = RunConfig(mode="teacher", passes=4, teacher=TeacherConfig())
    d = corpus["uart_tx"]
    run = annotate_design(
        d["files"],
        top=d["top"],
        cfg=cfg,
        store=store,
        teacher=Teacher(cfg.teacher, fake_client_cls(responder)),
    )
    assert {a.name for a in run.results_full["uart_tx"].anchors} == {"tx_valid", "state_q"}
    rounds = sorted(r.request["round"] for r in store.iter_records())
    assert rounds == [0, 1, 2]  # pass 1, pass 2 (changed), pass 3 (converged) -> stop before pass 4
    assert any("converged" in ln for ln in run.log)
    # A/B: first-round view of the same store
    first = annotate_design(
        d["files"],
        top=d["top"],
        cfg=RunConfig(mode="teacher", store_only=True, use_round="first", teacher=TeacherConfig()),
        store=store,
    )
    assert {a.name for a in first.results_full["uart_tx"].anchors} == {"tx_valid"}
