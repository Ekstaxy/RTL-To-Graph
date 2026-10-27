#!/usr/bin/env bash
# x4: install the one tool x4 needs beyond x3's toolchain: wavedrom-cli, into runs/.tools/wavedrom.
# Uses the pinned node from runs/.tools/x3/node (run x3's install.sh first if it is missing).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TOOLS="${RTL2D_TOOLS:-$ROOT/runs/.tools}"
NODE_BIN="$TOOLS/x3/node/bin"
if [ ! -x "$NODE_BIN/node" ]; then
  echo "node not found at $NODE_BIN; run pipeline/experiments/x3_tool_compare/install.sh" >&2
  exit 1
fi
mkdir -p "$TOOLS/wavedrom"
PATH="$NODE_BIN:$PATH" npm --prefix "$TOOLS/wavedrom" install --no-audit --no-fund \
  wavedrom-cli@3.2.0 wavedrom@3.5.0
PATH="$NODE_BIN:$PATH" node "$TOOLS/wavedrom/node_modules/wavedrom-cli/wavedrom-cli.js" --help \
  | head -3
