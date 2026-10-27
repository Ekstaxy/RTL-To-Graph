"""Clone the third-party RTL corpora used for validation into data/corpus/ at pinned commits.

    python scripts/fetch_corpus.py              # all
    python scripts/fetch_corpus.py picorv32     # some

The manifests (data/corpus/*.json) refer to these checkouts; they are not committed.
"""

import subprocess
import sys
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[1] / "data" / "corpus"
REPOS = {
    "picorv32": (
        "https://github.com/YosysHQ/picorv32.git",
        "ef203c2b0a3fb793280f5114941416c425c5b461",
    ),
    "RTLLM": (
        "https://github.com/hkust-zhiyao/RTLLM.git",
        "51ed553d0ffd32797a1a0a13e051656bf302c81f",
    ),
    "verilog-eval": (
        "https://github.com/NVlabs/verilog-eval.git",
        "c498220d0a52248f8e3fdffe279075215bde2da6",
    ),
    "verilog-axis": (
        "https://github.com/alexforencich/verilog-axis.git",
        "48ff7a7e2ef782cf778d47910cf85835c64b1bce",
    ),
    "verilog-uart": (
        "https://github.com/alexforencich/verilog-uart.git",
        "1b867e53af738e4a8bc7c839ca2f1c07f40382dc",
    ),
    "serv": ("https://github.com/olofk/serv.git", "f200eb2ed7b69ac1c6b8eddd47654522aeee5ce8"),
    # round 4 (2026-10-03): MIT (alexforencich), Apache-2.0 (wb2axip, biriscv),
    # SHL-0.51 (common_cells)
    "darkriscv": (
        "https://github.com/darklife/darkriscv.git",
        "974034aa8079039a36b89c14dcdfed575de183b7",
    ),
    "verilog-i2c": (
        "https://github.com/alexforencich/verilog-i2c.git",
        "a65be4045e898a52e791c6ee71f8f79a7cd2e129",
    ),
    "verilog-axi": (
        "https://github.com/alexforencich/verilog-axi.git",
        "516bd5dadc3365b7f9e225d2af8fe0b8d804fe53",
    ),
    "verilog-ethernet": (
        "https://github.com/alexforencich/verilog-ethernet.git",
        "77320a9471d19c7dd383914bc049e02d9f4f1ffb",
    ),
    "verilog-wishbone": (
        "https://github.com/alexforencich/verilog-wishbone.git",
        "d1fa24a0e5634160536c199eab42f1af720d14ff",
    ),
    "wb2axip": (
        "https://github.com/ZipCPU/wb2axip.git",
        "2e8d3bc2d26ddc33d1881022a2a2b9d3f0c16b9b",
    ),
    "biriscv": (
        "https://github.com/ultraembedded/biriscv.git",
        "6af9c4be5a0807d368eaad5e49af52322e31d073",
    ),
    "common_cells": (
        "https://github.com/pulp-platform/common_cells.git",
        "e73baaec2ca665cd80c3c384e9258e35242b829c",
    ),
}


def main(names: list[str]) -> None:
    for name in names or list(REPOS):
        url, rev = REPOS[name]
        dst = CORPUS / name
        if not dst.exists():
            subprocess.run(["git", "clone", "--quiet", url, str(dst)], check=True)
        subprocess.run(["git", "-C", str(dst), "checkout", "--quiet", rev], check=True)
        print(f"{name}: {rev[:10]}")


if __name__ == "__main__":
    main(sys.argv[1:])
