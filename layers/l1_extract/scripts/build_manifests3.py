"""Manifests for the round-4 corpora: one design per module, all files of the repo's RTL dir.

python scripts/build_manifests3.py      -> data/corpus/round4.json
"""

import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "data" / "corpus"
REPOS = {
    # repo: (rtl globs, include dirs, top-name filter)
    "verilog-i2c": (["rtl/*.v"], [], None),
    "verilog-axi": (["rtl/*.v"], [], None),
    "verilog-ethernet": (["rtl/*.v", "lib/axis/rtl/*.v"], [], None),
    "verilog-wishbone": (["rtl/*.v"], [], None),
    "wb2axip": (["rtl/*.v"], [], None),
    "biriscv": (["src/core/*.v"], ["biriscv/src/core"], None),
    "common_cells": (["src/*.sv"], ["common_cells/include"], None),
    "picorv32": (
        ["picosoc/spimemio.v", "picosoc/simpleuart.v", "picosoc/picosoc.v", "picorv32.v"],
        [],
        {"spimemio", "spimemio_xfer", "simpleuart", "picosoc"},
    ),
}
SKIP = re.compile(r"(^|_)(tb|test|bench|sim|wrap|wrapper|xilinx|altera)(_|$)", re.I)
HEADER = re.compile(r"(_pkg|_defs)$")
_INST = re.compile(r"^\s*(\w+)\s*(?:#\s*\(|\w+\s*(?:\[[^\]]*\]\s*)?\()", re.M)


def _strip(txt: str) -> str:
    return re.sub(r"//.*", "", re.sub(r"/\*.*?\*/", "", txt, flags=re.S))


def closure(top: str, defined: dict, uses: dict) -> list:
    """Files needed for `top`: its file plus files defining every instantiated module."""
    need, todo = set(), [top]
    while todo:
        m = todo.pop()
        f = defined.get(m)
        if f is None or f in need:
            continue
        need.add(f)
        todo += [u for u in uses[f] if u in defined]
    return need


def modules_in(f: Path) -> list[str]:
    txt = _strip(f.read_text(encoding="utf-8", errors="replace"))
    return re.findall(r"^\s*module\s+(?:automatic\s+)?(\w+)\s*(?:#|\(|;|$)", txt, re.M)


items = []
for repo, (globs, incs, only) in REPOS.items():
    files = sorted({f for g in globs for f in (root / repo).glob(g)})
    files = [f for f in files if not SKIP.search(f.stem)]
    headers = [f for f in files if HEADER.search(f.stem)]  # packages / `define files first
    defined, uses = {}, {}
    for f in files:
        txt = _strip(f.read_text(encoding="utf-8", errors="replace"))
        for m in modules_in(f):
            defined.setdefault(m, f)
        uses[f] = set(_INST.findall(txt))
    for f in files:
        for m in modules_in(f):
            if (only and m not in only) or SKIP.search(m) or defined[m] != f:
                continue
            need = closure(m, defined, uses)
            ordered = headers + [x for x in files if x in need and x not in headers]
            rel = [x.relative_to(root).as_posix() for x in ordered]
            items.append(
                {"name": f"{repo}_{m}", "files": rel, "top": m, "group": repo, "include_dirs": incs}
            )
(root / "round4.json").write_text(json.dumps(items, indent=1), encoding="utf-8")
print(len(items), "designs")
