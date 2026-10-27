"""Small helper: rasterize an SVG for the pages (rsvg-convert, optional)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def png_to(svg: Path, png: Path) -> None:
    exe = shutil.which("rsvg-convert")
    if exe:
        png.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([exe, "-w", "1600", str(svg), "-o", str(png)], capture_output=True,
                       timeout=120)
