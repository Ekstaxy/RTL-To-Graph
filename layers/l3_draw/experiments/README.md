# experiments/

Owned by this layer's owner. Repo-wide rules (docs/bootstrap.md §8):

1. One experiment per folder, named `<id>_<name>`, e.g. `n1_elk_baseline`.
2. Every experiment has a README following `docs/experiment_template.md`:
   hypothesis, measurement, pass/abandon criteria, results, conclusion.
3. May import this layer's `src/`, `rtl2d_contracts` and `rtl2d_eval`.
   Inputs come from `corpus/`; outputs go to `runs/`.

Experiment code needs no tests and is not run in CI. Promote to `src/` with tests when it becomes a feature.

Run: `uv run --package <this-package> python layers/<layer>/experiments/<exp>/run.py`
