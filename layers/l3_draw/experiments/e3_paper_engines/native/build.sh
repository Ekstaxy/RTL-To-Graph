#!/bin/sh
# Builds the two native helpers against adaptagrams installed under runs/.tools/adaptagrams.
# One-time install of adaptagrams (see README):
#   git clone https://github.com/mjwybrow/adaptagrams runs/.tools/src/adaptagrams
#   cd runs/.tools/src/adaptagrams/cola && autoreconf --install &&
#   ./configure --prefix=$PWD/../../../adaptagrams && make -j8 && make install
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../../../.." && pwd)
A="$ROOT/runs/.tools/adaptagrams"
OUT="$ROOT/runs/.tools/bin"
mkdir -p "$OUT"
for p in hola_run avoid_run; do
  g++ -O2 -std=c++14 -I"$A/include" "$HERE/$p.cpp" -L"$A/lib" \
      -ldialect -lcola -ltopology -lavoid -lvpsc -Wl,-rpath,"$A/lib" -o "$OUT/$p"
done
# libavoid's nudging asserts on some large inputs (orthogonal.cpp, freeSegmentID); a copy
# built with -DNDEBUG (runs/.tools/adaptagrams-nd, same configure plus CXXFLAGS="-O2
# -DNDEBUG") is used as a fallback. Its routes are checked by measure3 like any other.
N="$ROOT/runs/.tools/adaptagrams-nd"
if [ -d "$N/lib" ]; then
  g++ -O2 -std=c++14 -DNDEBUG -I"$N/include" "$HERE/avoid_run.cpp" -L"$N/lib" -lavoid \
      -Wl,-rpath,"$N/lib" -o "$OUT/avoid_run_nd"
fi
echo "built $OUT/hola_run $OUT/avoid_run $OUT/avoid_run_nd"
