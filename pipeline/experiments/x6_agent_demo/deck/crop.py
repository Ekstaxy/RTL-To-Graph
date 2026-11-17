"""Crop the part of each screenshot a slide is about: python crop.py (writes shots/c_*.png)"""
from pathlib import Path

from PIL import Image

S = Path(__file__).resolve().parent / "shots"
CROPS = {  # fractions of the 1440x900 page: (left, top, right, bottom)
    "01_input": (0.0, 0.065, 0.415, 0.76),   # the request and the agent's first steps
    "02_fsm": (0.435, 0.125, 0.985, 0.67),   # the proven state graph
    "03_block": (0.435, 0.125, 0.985, 0.625),  # the paper-style block diagram
    "04_timing": (0.0, 0.17, 0.415, 0.86),   # what the timing diagrams do and do not show
    "05_cpu": (0.0, 0.31, 0.415, 0.86),      # the transitions proven impossible
}
for n, (l, t, r, b) in CROPS.items():
    im = Image.open(S / f"{n}.png")
    W, H = im.size
    im.crop((int(l * W), int(t * H), int(r * W), int(b * H))).save(S / f"c_{n}.png")
    print(n, im.size)
