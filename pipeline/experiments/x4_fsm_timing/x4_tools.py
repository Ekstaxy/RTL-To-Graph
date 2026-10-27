"""x4: locate external tools (Yosys, sby, iverilog, Verilator, node, WaveDrom, Graphviz) and run
them under a memory cap. Everything lives under the git-ignored runs/.tools tree.

    uv run python pipeline/experiments/x4_fsm_timing/x4_tools.py --check

`RTL2D_TOOLS` overrides the tools root (default <repo>/runs/.tools).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TOOLS = Path(os.environ.get("RTL2D_TOOLS", ROOT / "runs" / ".tools"))
CAD = TOOLS / "x3" / "oss-cad-suite" / "bin"
NODE_BIN = TOOLS / "x3" / "node" / "bin"
WAVEDROM = TOOLS / "wavedrom" / "node_modules" / "wavedrom-cli" / "wavedrom-cli.js"
OUT = ROOT / "runs" / "x4_fsm_timing"
E8 = ROOT / "layers" / "l1_extract" / "experiments" / "e8_fsm_extra"
E9 = ROOT / "layers" / "l1_extract" / "experiments" / "e9_protocol_templates"
E4 = ROOT / "layers" / "l3_draw" / "experiments" / "e4_fsm_timing_draw"


def load(path: Path, name: str):
    """Import one experiment module from its file under a unique name (never via sys.path, so
    same-named modules of different experiments cannot collide)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def x4(name: str):
    """Load a module of this experiment (x4_fsm_timing/<name>.py)."""
    return load(HERE / f"{name}.py", f"x4_{name}" if not name.startswith("x4_") else name)


def tool_env() -> dict[str, str]:
    """Environment with OSS CAD Suite and node first on PATH (so L1's yosys_check also works)."""
    env = dict(os.environ)
    extra = [str(p) for p in (CAD, NODE_BIN) if p.is_dir()]
    env["PATH"] = os.pathsep.join([*extra, env.get("PATH", "")])
    env["RTL2D_TOOLS"] = str(TOOLS)
    return env


def export_path() -> None:
    """Put the tool directories on this process's PATH (call before using L1's yosys_check)."""
    os.environ.update(tool_env())


def which(name: str) -> str | None:
    for d in (CAD, NODE_BIN):
        p = d / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return shutil.which(name)


def node() -> str | None:
    return which("node")


def wavedrom_cmd() -> list[str] | None:
    n = node()
    if n and WAVEDROM.is_file():
        return [n, str(WAVEDROM)]
    return None


def _has_systemd_run() -> bool:
    if not shutil.which("systemd-run"):
        return False
    try:
        r = subprocess.run(
            ["systemd-run", "--scope", "--quiet", "-p", "MemoryMax=64M", "true"],
            capture_output=True, timeout=20,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_SYSTEMD: bool | None = None


def run_capped(
    cmd: list[str],
    *,
    cwd: str | Path | None = None,
    timeout: float = 300.0,
    mem: str = "50%",
    stdin: str | None = None,
) -> subprocess.CompletedProcess:
    """Run `cmd` with the tool PATH, a wall-clock timeout and (when available) a cgroup memory
    cap, so one oversize run cannot take the WSL VM down. Never raises on a non-zero exit; a
    timeout comes back as returncode 124 with the partial output."""
    global _SYSTEMD
    if _SYSTEMD is None:
        _SYSTEMD = _has_systemd_run()
    full = list(cmd)
    if _SYSTEMD:
        full = ["systemd-run", "--scope", "--quiet", "-p", f"MemoryMax={mem}",
                "-p", "MemorySwapMax=0", *full]
    try:
        return subprocess.run(
            full, cwd=cwd, env=tool_env(), capture_output=True, text=True,
            timeout=timeout, input=stdin,
        )
    except subprocess.TimeoutExpired as e:
        def _s(x):
            return x.decode(errors="replace") if isinstance(x, bytes) else (x or "")
        return subprocess.CompletedProcess(full, 124, _s(e.stdout), _s(e.stderr) + "\nTIMEOUT")


def _first_line(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=tool_env())
        txt = (r.stdout or r.stderr).strip().splitlines()
        return txt[0] if txt else f"exit {r.returncode}"
    except (OSError, subprocess.SubprocessError) as e:
        return f"error: {e}"


def versions() -> dict[str, str | None]:
    v: dict[str, str | None] = {}
    probes = {
        "yosys": ["-V"], "sby": ["--help"], "iverilog": ["-V"], "verilator": ["--version"],
        "yices-smt2": ["--version"], "node": ["--version"], "dot": ["-V"],
    }
    for name, args in probes.items():
        p = which(name)
        v[name] = _first_line([p, *args]) if p else None
    if v.get("sby"):
        v["sby"] = "present"
    wd = wavedrom_cmd()
    if wd:
        pkg = WAVEDROM.parent / "package.json"
        try:
            v["wavedrom-cli"] = json.loads(pkg.read_text())["version"]
        except (OSError, ValueError, KeyError):
            v["wavedrom-cli"] = "present"
    else:
        v["wavedrom-cli"] = None
    return v


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="print tool versions; exit 1 if any "
                    "required tool is missing")
    a = ap.parse_args(argv)
    v = versions()
    for k, s in v.items():
        print(f"{k:13s} {s if s else 'MISSING'}")
    required = ["yosys", "sby", "iverilog", "node", "dot", "wavedrom-cli"]
    missing = [k for k in required if not v.get(k)]
    if missing:
        print("missing:", ", ".join(missing), "(run pipeline/experiments/x4_fsm_timing/install.sh)")
    return 1 if (a.check and missing) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
