"""rtl2d_l1: RTL -> Selection.

Public API is ``extract()`` only. May import ``rtl2d_contracts`` and nothing else from this repo.

Internals (Stage 1, see ``layers/l1_extract/docs/SPEC.md``): slang elaboration -> typed
dependency graph -> entity tables -> semantic anchors (heuristic / teacher LLM / student)
-> trace region, plus FSM extraction. The full output (anchors.json, region.json, fsm.json)
is also available through the developer CLI ``python -m rtl2d_l1.cli``.
"""

from __future__ import annotations

import warnings
from pathlib import Path

__all__ = ["extract"]  # SelectionDraftWarning is importable but not part of the API

RTL_SUFFIXES = (".v", ".sv")


class SelectionDraftWarning(UserWarning):
    """The Selection contract is still v0-draft; extract() returns a plain dict."""


def extract(
    rtl_dir: Path,
    *,
    top: str | None = None,
    mode: str = "heuristic",
    out_dir: Path | None = None,
) -> dict:
    """RTL directory -> Selection (contract v0-draft, returned as a dict).

    Runs Stage 1 on every .v/.sv file under ``rtl_dir`` and maps the anchors onto the
    v0-draft fields of bootstrap §4.1 (``schema_version``, ``design``, ``signals[]``,
    ``modules[]``; entries carry ``name``, ``reason``, ``source_refs``), as proposed in
    docs/adr/0002. ``rtl2d_contracts.Selection`` has no fields yet, so a
    ``SelectionDraftWarning`` is emitted instead of failing.

    ``mode="heuristic"`` costs nothing; ``"teacher"`` calls the API (needs a key).
    ``out_dir`` additionally writes the full Stage 1 output (anchors.json, region.json, ...).
    """
    from rtl2d_contracts.version import SCHEMA_VERSION

    from .pipeline import RunConfig, annotate_design

    warnings.warn(
        "rtl2d_l1.extract(): Selection contract is still v0-draft (docs/adr/0002, proposed); "
        "returning a plain dict with the draft fields.",
        SelectionDraftWarning,
        stacklevel=2,
    )
    rtl_dir = Path(rtl_dir)
    files = sorted(str(p) for p in rtl_dir.rglob("*") if p.suffix in RTL_SUFFIXES)
    if not files:
        raise FileNotFoundError(f"no .v/.sv files under {rtl_dir}")

    run = annotate_design(files, top=top, cfg=RunConfig(mode=mode), out_dir=out_dir)
    tables = run.tables_by_module
    for msg in run.log:
        if "error" in msg.lower():
            warnings.warn(f"rtl2d_l1.extract(): {msg}", RuntimeWarning, stacklevel=2)

    def ref(file: str, *lines: int) -> str:
        try:
            f = Path(file).resolve().relative_to(rtl_dir.resolve()).as_posix()
        except ValueError:
            f = file
        return f"{f}:" + "-".join(str(x) for x in lines)

    modules, signals = [], []
    for mod, res in run.results.items():
        t = tables.get(mod)
        if t is None:
            continue
        modules.append(
            {
                "name": mod,
                "reason": res.module_summary or f"module {mod} ({res.source} selection)",
                "source_refs": [ref(t.file, t.line_start, t.line_end)],
            }
        )
        rows = t.by_id()
        for a in res.anchors:
            row = rows.get(a.id)
            lines = a.lines or ([row.line] if row is not None and row.line else [])
            score = f"score {a.score:.0f}, " if a.score is not None else ""
            reason = f"{a.role.value} ({score}{a.importance.value})"
            if a.why:
                reason += f": {a.why}"
            signals.append(
                {
                    "name": f"{res.canonical_instance}.{a.name}",
                    "reason": reason,
                    "source_refs": [ref(t.file, ln) for ln in lines],
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "design": run.design.tops[0].name if len(run.design.tops) == 1 else rtl_dir.name,
        "signals": signals,
        "modules": modules,
    }
