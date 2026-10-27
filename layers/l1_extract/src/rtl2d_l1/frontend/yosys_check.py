"""Optional cross-check of FSM detection against Yosys `fsm_detect` (SPEC §2).

Yosys is not on the main path (its SystemVerilog frontend is much weaker than
slang); it is an independent second opinion. On Windows it runs inside WSL.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

_FSM = re.compile(
    r"(?:Found FSM state register|Not marking) ([\w$\\.\[\]]+?)"
    r"(?: as FSM state register)?[:.]?\s*$",
    re.M,
)


def _to_wsl(p: Path) -> str:
    p = p.resolve()
    drive = p.drive.rstrip(":").lower()
    return f"/mnt/{drive}" + p.as_posix()[2:]


def yosys_fsm_candidates(
    files: list[str | os.PathLike], top: str | None = None, timeout: int = 300
) -> set[tuple[str, str]]:
    paths = [Path(f) for f in files]
    use_wsl = os.name == "nt"
    if not use_wsl and shutil.which("yosys") is None:
        raise RuntimeError("yosys not found")
    srcs = " ".join(_to_wsl(p) if use_wsl else str(p.resolve()) for p in paths)
    script = (
        f"read_verilog -sv {srcs}; "
        + (f"hierarchy -top {top}; " if top else "")
        + "proc; opt_clean; fsm_detect"
    )
    cmd = ["wsl", "--", "yosys", "-p", script] if use_wsl else ["yosys", "-p", script]
    r = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
    )
    if r.returncode != 0:
        tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
        raise RuntimeError("yosys failed: " + " | ".join(tail))
    out = set()
    for m in _FSM.finditer(r.stdout):
        full = m.group(1)
        if "." in full:
            mod, sig = full.split(".", 1)
            out.add((mod.lstrip("\\"), sig.lstrip("\\")))
    return out
