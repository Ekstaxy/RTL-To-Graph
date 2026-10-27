#!/usr/bin/env bash
# Install every tool x3 runs into runs/.tools/x3/ (gitignored). Linux x86-64 (WSL is fine).
# Needs: curl, git, python3 (+venv), graphviz `dot`, and root for the apt line.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
T="$ROOT/runs/.tools/x3"
mkdir -p "$T/src" "$T/vsix" "$T/bin"
cd "$T"

# --- system libraries: headless Chromium, PyGObject/Pango for Symbolator, fonts
if [ "$(id -u)" = 0 ]; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 libcairo2 libcups2 libdbus-1-3 \
    libdrm2 libgbm1 libglib2.0-0 libnspr4 libnss3 libpango-1.0-0 libwayland-client0 libx11-6 \
    libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 \
    fonts-liberation fonts-freefont-ttf fonts-noto-cjk python3-gi python3-gi-cairo \
    gir1.2-pango-1.0 python3-venv graphviz
fi

# --- Yosys + Verilator (OSS CAD Suite) and Node.js
[ -x oss-cad-suite/bin/yosys ] || {
  curl -sL -o ocs.tgz https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2026-10-16/oss-cad-suite-linux-x64-20261016.tgz
  tar xzf ocs.tgz && rm ocs.tgz; }
[ -x node/bin/node ] || {
  curl -sL -o node.tar.xz https://nodejs.org/dist/v24.22.0/node-v24.22.0-linux-x64.tar.xz
  tar xJf node.tar.xz && mv node-v24.22.0-linux-x64 node && rm node.tar.xz; }
export PATH="$T/node/bin:$PATH"

# --- sources
clone() { [ -d "src/$2" ] || git clone -q --depth 1 ${3:+-b "$3"} "https://github.com/$1.git" "src/$2"; }
clone nturley/netlistsvg netlistsvg
clone TerosTechnology/netlistsvg teros-netlistsvg hierarchy
clone TerosTechnology/vscode-terosHDL vscode-terosHDL
clone Nic30/d3-hwschematic d3-hwschematic
clone tilk/digitaljs digitaljs
clone tilk/yosys2digitaljs yosys2digitaljs
clone SymbiFlow/sphinxcontrib-hdl-diagrams sphinxcontrib-hdl-diagrams
clone zebreus/symbolator symbolator
[ -d src/verilator ] || {
  git clone -q --depth 1 --filter=blob:none --sparse https://github.com/verilator/verilator.git src/verilator
  git -C src/verilator sparse-checkout set examples/json_py; }

# --- JS builds. netlistsvg (dormant): dev deps no longer resolve, so runtime deps only + tsc 3.9
for d in netlistsvg teros-netlistsvg; do
  (cd "src/$d" && npm install --no-audit --no-fund --loglevel=error --legacy-peer-deps --omit=dev \
     && npx -y -p typescript@3.9.10 tsc || true)   # tsc reports @types/lodash noise; JS is emitted
  [ -f "src/$d/built/index.js" ]
done
(cd src/d3-hwschematic && npm install --no-audit --no-fund --loglevel=error && npm run build)
(cd src/digitaljs && npm install --no-audit --no-fund --loglevel=error && npx webpack --mode production)
(cd src/yosys2digitaljs && npm install --no-audit --no-fund --loglevel=error && npm run build)
printf '#!/bin/sh\nexec "$(dirname "$0")/../node/bin/node" "$(dirname "$0")/../src/netlistsvg/bin/netlistsvg.js" "$@"\n' > bin/netlistsvg
chmod +x bin/netlistsvg

# --- Python tools (system python for PyGObject). sphinxcontrib-hdl-diagrams pins Sphinx 4.5,
# whose helper extensions must be pinned back too.
[ -d pyenv ] || python3 -m venv --system-site-packages pyenv
pyenv/bin/pip install -q ./src/symbolator ./src/sphinxcontrib-hdl-diagrams sphinx \
  "sphinxcontrib-applehelp<1.0.5" "sphinxcontrib-devhelp<1.0.3" "sphinxcontrib-htmlhelp<2.0.2" \
  "sphinxcontrib-qthelp<1.0.4" "sphinxcontrib-serializinghtml<1.1.6" "alabaster<0.7.14"

# --- Digital-IDE 0.4.6 (0.5.0 ships its netlist viewer as 0-byte files)
[ -d vsix/dide046 ] || {
  curl -sL --compressed -o vsix/dide-0.4.6.vsix \
    "https://marketplace.visualstudio.com/_apis/public/gallery/publishers/sterben/vsextensions/fpga-support/0.4.6/vspackage"
  mkdir -p vsix/dide046 && (cd vsix/dide046 && unzip -q ../dide-0.4.6.vsix); }

# --- headless Chromium for the browser-only renderers
"${UVX:-uvx}" --from playwright==1.49.1 playwright install chromium
echo "x3 tools installed in $T"
