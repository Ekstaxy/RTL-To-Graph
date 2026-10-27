"""Draw a bridged diagram with the stage3 (L3) experiment renderer, for comparison.

Calls e1's `draw()` directly: e1's `work()` uses SIGALRM, which does not exist on Windows.
e1/run.py is loaded by file path because e0 also has a `run.py`.

    uv run --package rtl2d-l3 --with nodejs-wheel python \
        pipeline/experiments/x1_l1_to_l3/draw_l3.py OUT_DIR NAME COMBO [COMBO ...]
"""

import importlib.util
import json
import sys
from pathlib import Path

E1 = Path(__file__).resolve().parents[3] / "layers/l3_draw/experiments/e1_layout_matrix"
sys.path.insert(0, str(E1))
_spec = importlib.util.spec_from_file_location("l3run", E1 / "run.py")
l3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(l3)


def main(out: str, name: str, combos: list[str]) -> None:
    d = l3.spec.Diagram.model_validate_json(Path(f"{out}/{name}.diagram.json").read_text())
    h = json.loads(Path(f"{out}/{name}.hints.json").read_text())
    for combo in combos:
        svg, m, rt = l3.draw(d, h, combo, title=name)
        Path(f"{out}/{name}.{combo}.svg").write_text(svg)
        print(combo, {k: m[k] for k in list(m)[:10]}, "roundtrip issues", len(rt))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
