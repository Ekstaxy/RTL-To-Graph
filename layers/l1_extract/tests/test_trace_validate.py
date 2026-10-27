from rtl2d_l1.heuristic import heuristic_annotation, is_trivial
from rtl2d_l1.schema import Anchor, ModuleAnnotation, ModuleResult, VotedAnchor
from rtl2d_l1.taxonomy import Importance, Role, TraceHint
from rtl2d_l1.trace import compute_region, entity_nodes, typed_slice, uncovered_hotspots
from rtl2d_l1.validate import validate
from rtl2d_l1.vote import agreement, vote


def _a(id_, name, role=Role.CONTROL_FLAG, imp=Importance.major, trace=TraceHint.control_backward):
    return Anchor(id=id_, name=name, role=role, importance=imp, trace=trace, why="")


def test_validator_errors(built):
    t = built["uart_tx"][2]["uart_tx"]
    ann = ModuleAnnotation(
        anchors=[
            _a("E99", "nope"),
            _a("E12", "wrong_name"),
            _a("E1", "clk"),
            _a("E13", "shift_q"),
            _a("E13", "shift_q"),
        ]
    )
    rep = validate(ann, t)
    codes = [e.split(":")[0] for e in rep.errors]
    assert codes.count("E_UNKNOWN_ID") == 1
    assert "E_NAME_MISMATCH" in codes and "E_AUTO_ROLE" in codes and "E_DUP" in codes
    assert any(w.startswith("W_MISSED_FSM") for w in rep.warnings)


def test_slice_stops_at_registers(built):
    _, G, _ = built["uart_tx"]
    sl = typed_slice(G, "uart_tx.tx_ready", TraceHint.control_backward, depth=6, reg_hops=1)
    assert "uart_tx.state_q" in sl
    assert "uart_tx.state_d" not in sl  # behind the state register


def test_region_and_hotspots(built):
    _, G, ts = built["cache_ctrl"]
    t = ts["cache_ctrl"]
    res = {
        "cache_ctrl": ModuleResult(
            module="cache_ctrl",
            canonical_instance=t.canonical_instance,
            source="human",
            anchors=[
                VotedAnchor(
                    **_a(
                        "E3", "cpu_req_valid", Role.HANDSHAKE_VALID, trace=TraceHint.interface
                    ).model_dump()
                )
            ],
        )
    }
    reg = compute_region(G, ts, res, include_top_ports=False)
    assert "cache_ctrl.cpu_req_valid" in reg.nodes
    hot = uncovered_hotspots(G, t, reg)
    assert any("data_array" in h or "tag_array" in h for h in hot)
    full = compute_region(G, ts, res, include_top_ports=True)
    assert len(full.nodes) >= len(reg.nodes)


def test_entity_nodes_across_generate_instances(built):
    _, G, ts = built["soc_top"]
    keys = entity_nodes(G, ts["sync_fifo"], "E11")  # mem_q in all 4 fifo instances
    assert len(keys) == 4


def test_heuristic_and_trivial(built):
    t = built["cache_ctrl"][2]["cache_ctrl"]
    ann = heuristic_annotation(t)
    assert not validate(ann, t).errors
    assert not is_trivial(t)


def test_vote():
    s1 = ModuleAnnotation(anchors=[_a("E1", "a"), _a("E2", "b")])
    s2 = ModuleAnnotation(anchors=[_a("E1", "a", Role.ENABLE), _a("E3", "c")])
    s3 = ModuleAnnotation(anchors=[_a("E1", "a", Role.ENABLE), _a("E2", "b")])
    rep, voted = vote([s1, s2, s3])
    by = {a.id: a for a in voted}
    assert set(by) == {"E1", "E2"}
    assert by["E1"].role == Role.ENABLE and by["E1"].confidence == 1.0
    assert abs(by["E2"].confidence - 2 / 3) < 1e-3
    assert 0 < agreement([s1, s2, s3]) < 1
