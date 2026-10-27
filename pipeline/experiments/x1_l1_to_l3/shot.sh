#!/bin/sh
# shot.sh in.svg out.png : rasterize with headless Edge at the SVG's own size
E="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
W=$(grep -o 'viewBox="[^"]*"' "$1" | head -1 | awk '{print $3}'); H=$(grep -o 'viewBox="[^"]*"' "$1" | head -1 | awk '{print $4}' | tr -d '"')
"$E" --headless=new --disable-gpu --hide-scrollbars --window-size=${W%.*},${H%.*} --screenshot="$(cygpath -w "$PWD/$2")" "file:///$(cygpath -m "$PWD/$1")" 2>/dev/null
