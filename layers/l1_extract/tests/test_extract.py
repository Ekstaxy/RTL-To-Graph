import warnings
from pathlib import Path

import pytest

from rtl2d_l1 import SelectionDraftWarning, extract

ROOT = Path(__file__).resolve().parents[1]


def test_extract_warns_and_returns_draft_selection(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "uart_tx.sv").write_text((ROOT / "examples/rtl/uart_tx.sv").read_text(encoding="utf-8"))
    with pytest.warns(SelectionDraftWarning):
        sel = extract(rtl)
    assert set(sel) == {"schema_version", "design", "signals", "modules"}
    assert [m["name"] for m in sel["modules"]] == ["uart_tx"]
    names = {s["name"] for s in sel["signals"]}
    assert "uart_tx.state_q" in names
    for s in sel["signals"]:
        assert s["reason"] and all(":" in r for r in s["source_refs"])


def test_extract_empty_dir_raises(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SelectionDraftWarning)
        with pytest.raises(FileNotFoundError):
            extract(tmp_path)
