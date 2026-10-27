"""Bounded sequential equivalence check of two RTL versions with Yosys (runs in WSL on Windows).

  python scripts/equiv_check.py --gold a.v [a2.v ...] --gate b.v [b2.v ...] --top TOP
      [--reset rst_n] [--depth 20]

Both designs must have the same top name and identical port names/widths. The check builds a miter
(gold vs gate), applies the reset in the first cycle (both polarities are tried; a polarity that
proves equivalence is reported) and runs SAT-based BMC for `--depth` cycles over ALL input
sequences: every output must match in every cycle.  PASS = no counterexample up to depth.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def to_wsl(p: Path) -> str:
    p = p.resolve()
    if os.name != "nt":
        return str(p)
    return f"/mnt/{p.drive.rstrip(':').lower()}" + p.as_posix()[2:]


def ascii_copy(files: list[Path], tag: str, tmp: Path) -> list[Path]:
    """WSL paths with non-ASCII characters are fine for Yosys, but keep things simple and
    robust."""
    out = []
    d = tmp / tag
    d.mkdir(parents=True, exist_ok=True)
    for f in files:
        dst = d / f.name
        dst.write_bytes(f.read_bytes())
        out.append(dst)
    return out


def prep(files: list[Path], top: str, name: str, params: dict[str, str] | None = None) -> str:
    srcs = " ".join(to_wsl(f) for f in files)
    ch = "".join(f" -chparam {k} {v}" for k, v in (params or {}).items())
    return (
        f"read_verilog -sv -defer {srcs}; hierarchy -top {top}{ch}; "
        "proc; flatten; memory; opt_clean; "
        f"rename {top} {name}; design -stash {name}; "
    )


def run(
    gold: list[Path],
    gate: list[Path],
    top: str,
    reset: str | None,
    depth: int,
    params: dict[str, str] | None = None,
    reset_active: str | None = None,
) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as td:
        tmp = Path(td)
        g = ascii_copy(gold, "gold", tmp)
        h = ascii_copy(gate, "gate", tmp)
        base = (
            prep(g, top, "gold", params)
            + prep(h, top, "gate", params)
            + "design -copy-from gold -as gold gold; design -copy-from gate -as gate gate; "
            "miter -equiv -flatten -make_assert -ignore_gold_x gold gate miter; "
            "hierarchy -top miter; "
            "flatten; async2sync; opt -fast; "
        )
        if not reset:
            tries = [""]
        elif reset_active is not None:  # strict: reset really asserted in cycle 1
            tries = [f"-set-at 1 in_{reset} {reset_active}"]
        else:
            tries = [f"-set-at 1 in_{reset} 0", f"-set-at 1 in_{reset} 1"]

        def sat(opts: str, timeout: int) -> tuple[str, str]:
            cmd = (
                base + f"sat -verify -prove-asserts -set-init-zero {opts} -timeout {timeout} miter"
            )
            argv = (
                ["wsl", "--", "yosys", "-q", "-p", cmd]
                if os.name == "nt"
                else ["yosys", "-q", "-p", cmd]
            )
            r = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout + 120,
            )
            log = r.stdout + r.stderr
            if r.returncode == 0 and "proof did fail" not in log and "time out" not in log:
                return "ok", log
            if "proof did fail" in log:
                return "cex", log
            if "time out" in log or "timed out" in log:
                return "timeout", log
            return "error", log

        # strongest first: BMC from reset at full depth, then shallower BMC if the SAT problem
        # is too hard
        last, timeouts = "", 0
        for d in (depth, max(4, depth // 2), max(3, depth // 4)):
            cex = 0
            for t in tries:
                st, log = sat(f"-seq {d} {t}", 240)
                last = log
                if st == "ok":
                    strength = "full" if d == depth else "reduced"
                    return "PASS", f"BMC depth {d} ({strength}) from reset [{t or 'no reset'}]"
                if st == "error":
                    return "ERROR", "\n".join(
                        log.strip().splitlines()[-4:]
                    )  # parse/elaboration problem
                cex += st == "cex"
                timeouts += st == "timeout"
            if cex == len(tries):
                return "FAIL", f"counterexample within depth {d:d}\n" + "\n".join(
                    last.strip().splitlines()[-8:]
                )
        return (
            "TIMEOUT",
            f"no counterexample found, but SAT timed out down to depth {max(3, depth // 4)}",
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", nargs="+", required=True)
    ap.add_argument("--gate", nargs="+", required=True)
    ap.add_argument("--top", required=True)
    ap.add_argument("--reset", default=None, help="reset port name (both polarities are tried)")
    ap.add_argument("--depth", type=int, default=20)
    ap.add_argument(
        "--param",
        nargs="*",
        default=[],
        help="NAME=VALUE overrides applied to BOTH (shrink memories)",
    )
    ap.add_argument(
        "--reset-active",
        choices=["0", "1"],
        default=None,
        help=(
            "strict mode: assert reset with this level in cycle 1 (otherwise both levels are tried)"
        ),
    )
    a = ap.parse_args()
    params = dict(x.split("=", 1) for x in a.param)
    status, info = run(
        [Path(x) for x in a.gold],
        [Path(x) for x in a.gate],
        a.top,
        a.reset,
        a.depth,
        params,
        a.reset_active,
    )
    print(status, info)
    sys.exit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    main()
