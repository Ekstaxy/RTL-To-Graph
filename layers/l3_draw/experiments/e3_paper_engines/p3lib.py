"""Shared setup for e3: paths, tools, and access to e2's inputs (and through it e0/e1).

Module names avoid e0/e1/e2 names that land on sys.path.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
E2 = HERE.parent / "e2_class_engines"
sys.path.insert(0, str(E2))

import e1lib  # noqa: E402  (e0 / e1 on sys.path)
import inputs as e2inputs  # noqa: E402

ROOT = e1lib.ROOT
RUNS = ROOT / "runs" / "e3_paper_engines"
TOOLS = ROOT / "runs" / ".tools"
BIN = TOOLS / "bin"
COLA_JS = TOOLS / "cola" / "node_modules" / "webcola" / "dist" / "index.js"
D2 = TOOLS / "d2" / "bin" / "d2"
spec = e1lib.spec


def node() -> str:
    n = e1lib.ext._node()
    if not n:
        raise ValueError("node not found (run with --with nodejs-wheel)")
    return n


def need(path: Path, what: str) -> str:
    if not path.exists():
        raise ValueError(f"{what} not installed at {path} (see README)")
    return str(path)


def run(cmd: list[str], stdin: str, timeout: int = 120) -> str:
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def gv(prog: str) -> str:
    p = shutil.which(prog)
    if not p:
        raise ValueError(f"graphviz {prog} not installed")
    return p


def load(name: str):
    """(diagram, hints, sidecar) of an e2 input; writes e2's inputs first if needed."""
    if not (e1lib.RUNS / "inputs" / f"{name}.diagram.json").exists():
        e2inputs.write_all()
    return e2inputs.load(name)
