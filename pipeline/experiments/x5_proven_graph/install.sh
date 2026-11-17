#!/usr/bin/env bash
# x5 environment on Ubuntu (24.04 tested, also under WSL).
#
#   bash install.sh            # system packages if sudo works, then a Python venv with z3
#   source .venv/bin/activate  # afterwards, in every new shell
#   python x5.py doctor        # every tool found?
#   python x5.py selftest      # every expectation holds?
#
# The method was validated with Yosys 0.33, Icarus Verilog 12.0, z3 5.4.1 and Graphviz 2.43, which
# are what Ubuntu 24.04's packages and pip give. Other versions may work; run the self-test first.
set -euo pipefail
cd "$(dirname "$0")"

missing=()
for t in yosys yosys-abc iverilog vvp dot python3; do
  command -v "$t" >/dev/null 2>&1 || missing+=("$t")
done

if [ ${#missing[@]} -gt 0 ]; then
  echo "missing: ${missing[*]}"
  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null || [ "${X5_USE_SUDO:-}" = 1 ]; then
    sudo apt-get update
    sudo apt-get install -y yosys iverilog graphviz python3-venv
  else
    cat <<'EOF'
Install them with:
    sudo apt-get install -y yosys iverilog graphviz python3-venv
(or run this script again with X5_USE_SUDO=1 to let it ask for your password).
Without sudo: the OSS CAD Suite (https://github.com/YosysHQ/oss-cad-suite-build/releases) has
yosys, yosys-abc and iverilog in one folder; put its bin/ on PATH. It ships newer versions than the
ones x5 was validated with, so run `python x5.py selftest` and trust results only if it passes.
EOF
    exit 1
  fi
fi

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet "z3-solver==5.4.1" || .venv/bin/pip install --quiet z3-solver
.venv/bin/python x5.py doctor
echo
echo "Next: source .venv/bin/activate && python x5.py selftest"
