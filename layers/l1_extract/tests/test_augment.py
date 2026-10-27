from rtl2d_l1.augment import rename_variant, transfer_labels, transform_text
from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate


def test_transform_text_rules():
    src = '// state reg\nassign foo = bar; /* foo */\nsub u(.foo(foo)); $display("foo"); `foo\n'
    out = transform_text(src, {"foo": "n1", "bar": "n2"}, strip_comments=True)
    assert out.count("\n") == src.count("\n")  # line numbers preserved
    assert "assign n1 = n2;" in out
    assert ".foo(n1)" in out  # named port connection left alone
    assert '"foo"' in out and "`foo" in out
    assert "state reg" not in out


def test_rename_preserves_ids_and_transfers_labels(tmp_path, corpus, built):
    d = corpus["ugly_mul"]
    t = built["ugly_mul"][2]["ugly_mul"]
    v = rename_variant(t, tmp_path, include_ports=True, seed=3)
    vt = build_entity_tables(build_graph(elaborate([v.path], top=v.top)))[0]
    assert v.top and v.top != d["top"]  # module name is obfuscated too
    assert [r.id for r in vt.rows] == [r.id for r in t.rows]
    for r0, r1 in zip(t.rows, vt.rows, strict=False):
        assert r1.name == v.mapping.get(r0.name, r0.name)
    assert [r.fsm_candidate for r in vt.rows] == [r.fsm_candidate for r in t.rows]
    g = transfer_labels({"anchors": [{"id": "E8", "name": "m"}]}, v.mapping)
    assert g["anchors"][0]["name"] == v.mapping["m"]


def test_blind_variant_has_identical_structural_features(tmp_path, corpus, built):
    """Obfuscating every name (module, enums, params, signals) must not change what the frontend
    tells the model: auto roles (clock/reset), FSM candidates, kinds and fan-outs are structural."""
    for name in ("cache_ctrl", "ugly_mul", "uart_tx"):
        t = built[name][2][name]
        v = rename_variant(t, tmp_path / name, include_ports=True, seed=5)
        vt = build_entity_tables(build_graph(elaborate([v.path], top=v.top)))[0]

        def feat(tb):
            return [
                (r.id, r.kind, r.auto_role, r.fsm_candidate, r.fanout, r.ctrl_fanout)
                for r in tb.rows
            ]

        assert feat(vt) == feat(t)
