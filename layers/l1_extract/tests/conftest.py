import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "examples" / "rtl"


@pytest.fixture(scope="session")
def corpus():
    items = json.loads((ROOT / "examples" / "corpus.json").read_text(encoding="utf-8"))
    return {
        it["name"]: {"files": [str(ROOT / "examples" / f) for f in it["files"]], "top": it["top"]}
        for it in items
    }


@pytest.fixture(scope="session")
def built(corpus):
    """name -> (design, graph, {module: table})"""
    from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate

    out = {}
    for name, d in corpus.items():
        des = elaborate(d["files"], top=d["top"])
        G = build_graph(des)
        out[name] = (des, G, {t.module: t for t in build_entity_tables(G)})
    return out


# ------------------------------------------------------------- fake Anthropic
class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return {k: v for k, v in self.__dict__.items()}


class _Usage:
    input_tokens = 1000
    output_tokens = 500
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _Msg:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_Block("thinking", thinking="", signature="sig"), _Block("text", text=text)]
        self.stop_reason = stop_reason
        self.stop_details = None
        self.usage = _Usage()


class _Stream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


class FakeClient:
    """responder(params) -> annotation dict (or str for raw text)."""

    def __init__(self, responder):
        self.responder = responder
        self.calls = []
        client = self

        class _Messages:
            def stream(self, **params):
                client.calls.append(params)
                r = client.responder(params)
                return _Stream(_Msg(r if isinstance(r, str) else json.dumps(r)))

        class _Beta:
            messages = _Messages()

        self.beta = _Beta()


@pytest.fixture
def fake_client_cls():
    return FakeClient
