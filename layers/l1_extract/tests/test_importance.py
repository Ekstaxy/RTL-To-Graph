from rtl2d_l1.controls import Controls, apply_view
from rtl2d_l1.importance import (
    SCORE_HIGH,
    SCORE_MEDIUM,
    STRUCT_FEATURES,
    calibrated_structural,
    combined_score,
    module_features,
    score_module,
)
from rtl2d_l1.pipeline import RunConfig, annotate_design
from rtl2d_l1.schema import ModuleResult, VotedAnchor
from rtl2d_l1.taxonomy import Importance, Level, Role, TraceHint


def test_features_cover_every_selectable_entity(built):
    _, G, tables = built["cache_ctrl"]
    t = tables["cache_ctrl"]
    f = module_features(G, t)
    sel = {r.id for r in t.rows if r.kind != "inst" and not r.auto_role}
    assert set(f) == sel
    assert all(set(v) == set(STRUCT_FEATURES) for v in f.values())
    assert all(0.0 <= v["ctrl_reach"] <= 1.0 and 0.0 <= v["back_cone"] <= 1.0 for v in f.values())


def test_score_scale_and_monotone_in_tier():
    assert (
        combined_score(50.0, "critical")
        > combined_score(50.0, "major")
        > combined_score(50.0, "minor")
    )
    # with a tier: critical never drops below HIGH; structure can promote by at most one level
    assert combined_score(0.0, "critical") >= SCORE_HIGH
    assert SCORE_MEDIUM <= combined_score(100.0, "minor") < SCORE_HIGH
    assert (
        SCORE_MEDIUM <= combined_score(0.0, "major") < SCORE_HIGH <= combined_score(100.0, "major")
    )
    # structure-only calibration is monotone and maps onto the same thresholds
    xs = [calibrated_structural(x) for x in range(0, 101, 5)]
    assert xs == sorted(xs) and xs[0] == 0.0 and xs[-1] == 100.0
    assert abs(calibrated_structural(60.4) - SCORE_HIGH) < 1e-9


def test_pipeline_attaches_scores_and_views_use_them(corpus):
    d = corpus["uart_tx"]
    run = annotate_design(d["files"], top=d["top"], cfg=RunConfig(mode="heuristic"))
    res = run.results_full["uart_tx"]
    assert res.anchors and all(a.score is not None for a in res.anchors)
    assert all(0 <= a.score <= 100 and 0 <= a.struct_score <= 100 for a in res.anchors)
    for mode in ("score", "tier", "structure"):
        hi = {a.id for a in apply_view(res, Controls(level=Level.HIGH, importance=mode)).anchors}
        med = {a.id for a in apply_view(res, Controls(level=Level.MEDIUM, importance=mode)).anchors}
        assert hi <= med  # views stay nested
    top = apply_view(res, Controls(level=Level.LOW, max_anchors=2)).anchors
    best = sorted(res.anchors, key=lambda a: -a.score)[:2]
    assert {a.id for a in top} == {a.id for a in best}


def test_structure_mode_ignores_tier(built):
    _, G, tables = built["uart_tx"]
    t = tables["uart_tx"]
    rid = next(r.id for r in t.rows if r.name == "state_q")
    mk = lambda imp: VotedAnchor(  # noqa: E731
        id=rid,
        name="state_q",
        role=Role.FSM_STATE,
        importance=imp,
        trace=TraceHint.control_backward,
    )
    lo, hi = (
        score_module(G, t, [mk(Importance.minor)]),
        score_module(G, t, [mk(Importance.critical)]),
    )
    assert lo[rid][0] < hi[rid][0]  # combined score follows the tier
    assert lo[rid][1] == hi[rid][1]  # structure-only score does not
    res = ModuleResult(module="uart_tx", canonical_instance="uart_tx", source="teacher")
    assert apply_view(res, Controls(importance="structure")).anchors == []
