"""Build the L3 input set: seed cases x variants, each checked with spec.validate.

Seeds: files in cases/, synthetic pipelines (gen.py), cases drafted from reference figures
(real.py), other shapes and edge cases (topo.py).
Output: runs/e0_reference_inputs/inputs/{valid,invalid}/<seed>__<variant>.diagram.json
        runs/e0_reference_inputs/inputs/hints/<seed>.hints.json  (experiment-local format)

Run: uv run --package rtl2d-l3 python layers/l3_draw/experiments/e0_reference_inputs/run.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import gen
import real
import spec
import topo
import variants

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[3] / "runs" / "e0_reference_inputs" / "inputs"

SYNTHETIC = {
    "pipe2": dict(stages=2, forwards=0),
    "pipe8_fwd2": dict(stages=8, forwards=2),
    "pipe16_w64": dict(stages=16, width=64, forwards=3),
    "pipe4_noctrl": dict(stages=4, controller=False),
    "pipe4_hier": dict(stages=4, hier=True),
}


Hints = dict[str, dict[str, dict[str, object]]]


def seeds() -> dict[str, tuple[spec.Diagram, Hints]]:
    """Seed name -> (diagram, hints). Hints may be empty."""
    out: dict[str, tuple[spec.Diagram, Hints]] = {}
    for path in sorted((HERE / "cases").glob("*.diagram.json")):
        d, issues = spec.load(path)
        if issues:
            sys.exit(f"seed {path.name} is not valid:\n  " + "\n  ".join(issues))
        out[path.name.removesuffix(".diagram.json")] = (d, gen.pipeline_hints(d))
    for name, kwargs in SYNTHETIC.items():
        d = gen.pipeline(**kwargs)
        out[name] = (d, gen.pipeline_hints(d))
    for name, fn in {**real.REAL, **topo.SHAPES, **topo.EDGE}.items():
        out[name] = fn()
    return out


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    failures = 0
    print(f"{'file':44} {'blocks':>6} {'ports':>6} {'nets':>5}  check")
    for seed_name, (seed, hints) in seeds().items():
        (OUT / "hints").mkdir(parents=True, exist_ok=True)
        (OUT / "hints" / f"{seed_name}.hints.json").write_text(json.dumps(hints, indent=2) + "\n")
        for group, table in (("valid", variants.VALID), ("invalid", variants.INVALID)):
            for var_name, fn in table.items():
                if var_name == "bad_parent_cycle" and len(seed.blocks) < 2:
                    continue
                try:
                    d = fn(seed)
                except IndexError:  # variant needs a net or block the seed does not have
                    continue
                issues = spec.validate(d)
                as_expected = bool(issues) == (group == "invalid")
                failures += not as_expected
                name = f"{seed_name}__{var_name}"
                spec.dump(d, OUT / group / f"{name}.diagram.json")
                if group == "valid" or not as_expected:
                    verdict = "ok" if as_expected else f"UNEXPECTED: {issues or 'no issue found'}"
                    print(
                        f"{name:44} {len(d.blocks):6} {len(d.ports):6} {len(d.nets):5}  {verdict}"
                    )
    n_valid = len(list((OUT / "valid").glob("*.json")))
    n_invalid = len(list((OUT / "invalid").glob("*.json")))
    print(f"\n{n_valid} valid, {n_invalid} invalid (each caught) -> {OUT}")
    print(f"unexpected results: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
