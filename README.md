# rtl2diagram

Turn RTL into a readable hardware architecture diagram, through three independently owned layers:

```
RTL ──L1.extract──▶ Selection ──L2.build_spec──▶ Diagram ──L3.draw──▶ SVG
```

## Install
```
uv sync --all-packages
```

## Run the pipe4 example (L1/L2 from fixtures)
```
uv run rtl2d run corpus/pipe4 --fixture l1,l2
```

## How the repo is organised

Each stage is its own Python package with one owner. Stages never import each other.
They share one data-format package (`contracts/`), and one package (`pipeline/`) wires
them together. Everything lives in a single uv workspace: one virtualenv, one lockfile,
one `uv run pytest`.

```
RTL-To-Graph/
├── contracts/      shared data formats (pydantic)      everyone's
├── layers/
│   ├── l1_extract/ RTL → Selection                     owner 1
│   ├── l2_spec/    Selection → Diagram                 owner 2
│   └── l3_draw/    Diagram → SVG                       owner 3
├── pipeline/       wires L1 → L2 → L3, `rtl2d` CLI
├── eval/           cross-layer metrics (round-trip)
├── corpus/         test cases + expected output at each boundary
├── tests/          repo-wide rule checks
├── docs/           design spec, ADRs, templates
├── runs/           per-run output, git-ignored
└── .github/        CI + CODEOWNERS
```

### contracts/
The only package every layer imports. Pydantic models for each boundary:
`selection.py` (L1→L2), `diagram.py` (L2→L3), `layout.py` (layout hints/overrides),
`render.py` (SVG attribute convention used by round-trip). `validate.py` runs checks a
schema cannot express (unique IDs, net endpoints exist, widths match). `export_schema.py`
writes JSON Schema into `schemas/`, which is committed so CI can catch drift.
Any change needs an ADR, a `SCHEMA_VERSION` bump and a `CHANGELOG.md` entry.

### layers/
One package per stage, all the same shape:

| path | purpose |
|---|---|
| `src/rtl2d_lN/__init__.py` | the only public functions: `extract`, `build_spec` + `verify`, `draw` |
| `tests/` | that layer's tests |
| `experiments/` | the owner's sandbox; one folder per experiment, README required, not in CI |
| `CLAUDE.md` | that layer's inputs, outputs, allowed dependencies and taboos |

### pipeline/
The single place that knows how the layers connect. `run.py` calls the three functions
in order, validating and saving each result to `runs/`. `fixtures.py` reads
`corpus/<case>/expected/` so unimplemented layers can be skipped with `--fixture`.
`cli.py` provides `rtl2d run` and `rtl2d check`. This is what lets owners work in
parallel: L3's owner can always run with `--fixture l1,l2`.

### eval/
Quality metrics that span layers. `roundtrip.py` parses an SVG back into blocks, ports
and nets and diffs it against the Diagram. Depends only on `contracts`, so any layer's
experiments can use it.

### corpus/
Test cases. Each has `rtl/` plus `expected/` output at every boundary, and a `notes.md`
saying which files are hand-written. These files are the source of truth for the
contracts. Never edit `expected/` to make a test pass. Layer code must not read this
folder; only `pipeline/` and tests do.

### tests/
`test_layer_boundaries.py` scans every package's imports with `ast` and fails on any
cross-layer import. uv does not enforce this (all packages share one environment), so
this test is the real guard.

### docs/
`bootstrap.md` is the full design spec. `adr/` records architecture decisions.
`experiment_template.md` is the README format every experiment follows.

## Dependency rules

| package | may import |
|---|---|
| `rtl2d_contracts` | stdlib, pydantic |
| `rtl2d_l1`, `rtl2d_l2`, `rtl2d_l3` | `rtl2d_contracts` |
| `rtl2d_eval` | `rtl2d_contracts` |
| `rtl2d_pipeline` | everything |
| `layers/*/experiments/` | own layer, `rtl2d_contracts`, `rtl2d_eval` |

## Everyday commands

```
uv run pytest                                     # all tests
uv run --package rtl2d-l3 pytest layers/l3_draw   # one package
uv run ruff check .                               # lint
uv run python -m rtl2d_contracts.export_schema    # regenerate contracts/schemas/
```

See `docs/bootstrap.md` for the full design and `CLAUDE.md` for the rules Claude follows.
