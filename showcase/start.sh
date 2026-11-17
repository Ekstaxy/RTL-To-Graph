#!/bin/sh
# Unpack RTL-To-Graph-showcase.zip next to this script (again whenever the zip is newer) and open the results page.
set -e
cd "$(dirname "$0")"
z=RTL-To-Graph-showcase.zip
d=RTL-To-Graph-showcase
if [ ! -f "$d/.unpacked" ] || [ "$z" -nt "$d/.unpacked" ]; then
  echo "Unpacking $z ..."
  rm -rf "$d"
  if command -v unzip >/dev/null 2>&1; then unzip -q "$z"; else python3 -m zipfile -e "$z" .; fi
  date > "$d/.unpacked"
fi
page="$PWD/$d/proof.html"
if [ "$(uname)" = Darwin ]; then
  open "$page"
elif command -v wslpath >/dev/null 2>&1; then
  explorer.exe "$(wslpath -w "$page")" || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$page" >/dev/null 2>&1 &
else
  echo "Open this file in a browser: $page"
fi
