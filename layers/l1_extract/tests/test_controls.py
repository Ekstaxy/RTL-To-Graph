from rtl2d_l1.controls import Controls, apply_view
from rtl2d_l1.schema import Group, ModuleResult, VotedAnchor
from rtl2d_l1.taxonomy import Importance, Level, Role, TraceHint
from rtl2d_l1.trace import compute_region


def _res(t):
    rows = {r.name: r.id for r in t.rows}
    spec = [
        ("tx_valid", Role.HANDSHAKE_VALID, Importance.critical),
        ("tx_ready", Role.HANDSHAKE_READY, Importance.critical),
        ("state_q", Role.FSM_STATE, Importance.critical),
        ("baud_cnt_q", Role.COUNTER, Importance.major),
        ("shift_q", Role.STORAGE, Importance.major),
        ("bit_idx_q", Role.COUNTER, Importance.minor),
        ("baud_tick", Role.CONTROL_FLAG, Importance.minor),
    ]
    anchors = [
        VotedAnchor(
            id=rows[n], name=n, role=r, importance=i, trace=TraceHint.control_backward, why=""
        )
        for n, r, i in spec
    ]
    groups = [
        Group(name="ctrl", kind="CONTROLLER", anchor_ids=[rows["state_q"]]),
        Group(name="ser", kind="SERIALIZER", anchor_ids=[rows["shift_q"], rows["bit_idx_q"]]),
    ]
    return ModuleResult(
        module=t.module,
        canonical_instance=t.canonical_instance,
        source="human",
        anchors=anchors,
        groups=groups,
    )


def test_levels_are_nested(built):
    _, G, ts = built["uart_tx"]
    t = ts["uart_tx"]
    full = _res(t)
    sets, regions = {}, {}
    for lv in Level:
        v = apply_view(full, Controls(level=lv), t)
        sets[lv] = {a.id for a in v.anchors}
        regions[lv] = set(compute_region(G, ts, {t.module: v}, level=lv).nodes)
    assert sets[Level.HIGH] < sets[Level.MEDIUM] < sets[Level.LOW]
    assert regions[Level.HIGH] <= regions[Level.MEDIUM] <= regions[Level.LOW]


def test_knobs(built):
    t = built["uart_tx"][2]["uart_tx"]
    full = _res(t)
    v = apply_view(full, Controls(level=Level.LOW, max_anchors=3), t)
    assert {a.importance for a in v.anchors} == {Importance.critical} and len(v.anchors) == 3
    v = apply_view(full, Controls(level=Level.LOW, hide_interfaces=True), t)
    assert not any(a.role.value.startswith(("HANDSHAKE", "INTERFACE")) for a in v.anchors)
    v = apply_view(full, Controls.preset("control"), t)
    assert {a.role for a in v.anchors} <= {
        Role.FSM_STATE,
        Role.COUNTER,
        Role.HANDSHAKE_VALID,
        Role.HANDSHAKE_READY,
    }
    # groups whose anchors were all filtered out disappear; partially kept groups are trimmed
    v = apply_view(full, Controls(level=Level.MEDIUM), t)
    ser = [g for g in v.groups if g.name == "ser"][0]
    assert ser.anchor_ids == [a.id for a in full.anchors if a.name == "shift_q"]


def test_threshold_knob_monotone(built):
    _, G, ts = built["cache_ctrl"]
    t = ts["cache_ctrl"]
    rows = {r.name: r.id for r in t.rows}
    res = ModuleResult(
        module=t.module,
        canonical_instance=t.canonical_instance,
        source="human",
        anchors=[
            VotedAnchor(
                id=rows["state_q"],
                name="state_q",
                role=Role.FSM_STATE,
                importance=Importance.critical,
                trace=TraceHint.control_backward,
                why="",
            )
        ],
    )
    sizes = [
        len(compute_region(G, ts, {t.module: res}, threshold=th, include_top_ports=False).nodes)
        for th in (0.9, 0.5, 0.2, 0.05)
    ]
    assert sizes == sorted(sizes)


def test_vote_keeps_evidence_lines():
    from rtl2d_l1.schema import Anchor, ModuleAnnotation
    from rtl2d_l1.vote import vote

    a = Anchor(
        id="E3",
        name="x",
        role=Role.FSM_STATE,
        importance=Importance.critical,
        trace=TraceHint.control_backward,
        lines=[12, 14],
    )
    b = a.model_copy(update={"lines": [14, 20]})
    _, voted = vote([ModuleAnnotation(anchors=[a]), ModuleAnnotation(anchors=[b])])
    assert voted[0].lines == [12, 14, 20]
