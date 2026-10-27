"""Simulate the core with Yosys `sim` (WSL on Windows) and check the result-port writes.

python check_sim.py        -> expects [56, 123]
"""

import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run_yosys() -> None:
    if os.name == "nt":
        drive, rest = str(HERE)[0].lower(), HERE.as_posix()[2:]
        cmd = ["wsl", "-e", "bash", "-lc", f"cd /mnt/{drive}{rest} && yosys -q -s sim.ys"]
    else:
        cmd = ["yosys", "-q", "-s", "sim.ys"]
    subprocess.run(cmd, cwd=HERE, check=True)


def result_writes(vcd: Path) -> list[int]:
    lines = vcd.read_text().splitlines()
    ids = {}
    for ln in lines:
        m = re.match(r"\$var \w+ \d+ (\S+) (\S+)", ln)
        if m and m.group(2) in ("result", "result_valid", "clk"):
            ids[m.group(1)] = m.group(2)
    vals, out = {}, []
    for ln in lines:
        m = re.match(r"b([01xz]+) (\S+)", ln) or re.match(r"([01xz])(\S+)$", ln)
        if m and m.group(2) in ids:
            name = ids[m.group(2)]
            vals[name] = m.group(1)
            if name == "clk" and m.group(1) == "1" and vals.get("result_valid") == "1":
                out.append(int(vals["result"], 2))
    return out


if __name__ == "__main__":
    run_yosys()
    got = result_writes(HERE / "sim.vcd")
    print("result writes:", got)
    assert got == [56, 123], got
    print("PASS")
