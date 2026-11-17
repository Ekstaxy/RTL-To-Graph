#!/bin/sh
# RTL-To-Graph agent demo on macOS / Linux / WSL. Needs python3 and an Anthropic API key.
set -e
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
if ! grep -q '^ANTHROPIC_API_KEY=..' .env; then
  echo "Put your Anthropic API key after ANTHROPIC_API_KEY= in $(pwd)/.env, then run this again."
  exit 1
fi
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --disable-pip-version-check anthropic
if [ ! -f cache/.unpacked ] || [ demo_cache.zip -nt cache/.unpacked ]; then
  echo "Unpacking demo_cache.zip ..."
  rm -rf cache
  python3 -m zipfile -e demo_cache.zip cache
  date > cache/.unpacked
fi
echo "Starting http://localhost:8765  (Ctrl+C to stop)"
( sleep 3; { command -v open >/dev/null && open http://localhost:8765; } || { command -v xdg-open >/dev/null && xdg-open http://localhost:8765; } || true ) >/dev/null 2>&1 &
exec .venv/bin/python server.py
