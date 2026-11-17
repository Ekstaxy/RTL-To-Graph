#!/usr/bin/env bash
# Start the RTL-To-Graph agent demo (WSL / Linux). Then open http://localhost:8765
cd "$(dirname "$0")"
PY="${X5_AGENT_PY:-$HOME/rtl2d-demo/agentenv/bin/python}"
if [ ! -x "$PY" ]; then
  python3 -m venv "$HOME/rtl2d-demo/agentenv" && "$HOME/rtl2d-demo/agentenv/bin/pip" install -q anthropic "z3-solver==5.4.1"
  PY="$HOME/rtl2d-demo/agentenv/bin/python"
fi
exec "$PY" server.py
