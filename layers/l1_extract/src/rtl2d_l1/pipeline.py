"""End-to-end Stage 1 pipeline: RTL -> graph -> entity tables -> anchors -> region.

Modes
  heuristic : no API calls (baseline / trivial modules)
  teacher   : teacher with retry, optional k-voting and refine round
              (store_only=True: never call the API; use Run Store results, heuristic otherwise)
  dry-run   : build every teacher request and write it to disk, no API calls
  plan      : wave planning for batch / session annotation: collect the round-0 units whose
              children are already done; parents of pending modules wait for a later wave

The teacher always annotates at full detail (LOW); user Controls derive the views
(SPEC §4.5). Parents see their children only through *round-0* child results, so a
refine round on a child never invalidates the parent's cached work unit.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .controls import Controls, apply_view, region_for
from .frontend import DesignGraph, EntityTable, build_entity_tables, build_graph, elaborate
from .frontend.elab import SLANG_VERSION, Design
from .heuristic import heuristic_annotation, is_trivial
from .importance import attach_scores
from .llm.prompt import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    audit_message,
    privileged_block,
    refine_message,
    unit_hash,
    user_message,
)
from .llm.teacher import Outcome, Teacher, TeacherConfig, parse_annotation
from .schema import AnchorsFile, ModuleAnnotation, ModuleResult, VotedAnchor
from .store import RunRecord, RunStore
from .taxonomy import Level
from .trace import compute_region, uncovered_hotspots
from .validate import validate
from .versions import TAXONOMY_VERSION
from .vote import agreement, vote

REFINE_WARNINGS = ("W_MISSED_FSM", "W_FSM_NOT_STATE", "W_DEAD", "W_STORAGE_SHAPE")
ANN_LEVEL = Level.LOW  # annotation is always full-detail


@dataclass
class RunConfig:
    mode: str = "heuristic"  # heuristic | teacher | dry-run | plan
    level: Level = Level.MEDIUM  # view level (shortcut for controls.level)
    k: int = 1
    refine: bool = True
    force_api_for_trivial: bool = False
    budget_usd: float | None = None
    store_only: bool = False
    passes: int = 1  # >1: multi-pass self-audit until converged (SPEC §7.3b)
    use_round: str = "final"  # final | first: which round of each sample to use (A/B evaluation)
    targets: frozenset = frozenset(
        {"block"}
    )  # which diagrams to prepare data for: block | fsm | timing
    teacher: TeacherConfig = field(default_factory=TeacherConfig)
    controls: Controls | None = None

    def __post_init__(self):
        if self.controls is None:
            self.controls = Controls(level=self.level)
        self.level = self.controls.level


@dataclass
class DesignRun:
    design: Design
    graph: DesignGraph
    tables: list[EntityTable]
    results_full: dict[str, ModuleResult]
    results: dict[str, ModuleResult]  # view after Controls
    region: object
    log: list[str]
    controls: Controls
    plan: list[dict] = field(default_factory=list)
    fsms: list = field(default_factory=list)  # target "fsm": deterministic FSM extraction
    timing: dict | None = None  # target "timing": placeholder (interfaces to trace later)
    targets: frozenset = frozenset({"block"})

    @property
    def tables_by_module(self) -> dict[str, EntityTable]:
        return {t.module: t for t in self.tables}


class BudgetExceeded(RuntimeError):
    pass


def _result_from(
    table: EntityTable,
    rep: ModuleAnnotation,
    voted: list[VotedAnchor],
    source: str,
    run_ids: list[str],
    warnings: list[str],
) -> ModuleResult:
    return ModuleResult(
        module=table.module,
        canonical_instance=table.canonical_instance,
        source=source,
        level=ANN_LEVEL,
        module_summary=rep.module_summary,
        anchors=voted,
        groups=rep.groups,
        interfaces=rep.interfaces,
        run_ids=run_ids,
        warnings=warnings,
    )


def _heur(t: EntityTable, why: str, run_ids=None) -> ModuleResult:
    ann = heuristic_annotation(t, ANN_LEVEL)
    rep = validate(ann, t, ANN_LEVEL)
    return _result_from(
        t,
        ann,
        [VotedAnchor(**a.model_dump()) for a in ann.anchors],
        "heuristic",
        run_ids or [],
        [why] + rep.warnings,
    )


def module_findings(graph: DesignGraph, table: EntityTable, ann: ModuleAnnotation) -> list[str]:
    """Validator warnings + trace-engine hotspots (refine-round feedback)."""
    rep = validate(ann, table, ANN_LEVEL)
    findings = [w for w in rep.warnings if w.startswith(REFINE_WARNINGS)]
    voted = [VotedAnchor(**a.model_dump()) for a in ann.anchors]
    res = {
        table.module: ModuleResult(
            module=table.module,
            canonical_instance=table.canonical_instance,
            source="teacher",
            anchors=voted,
        )
    }
    region = compute_region(
        graph, {table.module: table}, res, level=Level.LOW, include_top_ports=False
    )
    findings += uncovered_hotspots(graph, table, region)
    return sorted(set(findings))


def _sig(ann: ModuleAnnotation) -> list[tuple]:
    return sorted((a.id, a.role.value, a.importance.value) for a in ann.anchors)


def _rebuild(
    um: str, ann: ModuleAnnotation, t: EntityTable, spec: str | None, top_defs: list[str]
) -> Outcome:
    """Conversation state for a sample that came from the Run Store (no thinking blocks to
    preserve)."""
    priv = privileged_block(spec, t.module, top_defs) if spec else ""
    return Outcome(
        annotation=ann,
        report=validate(ann, t, ANN_LEVEL),
        transcript=[
            {"role": "user", "content": um},
            {"role": "assistant", "content": ann.model_dump_json()},
        ],
        api_messages=[
            {"role": "user", "content": um + priv},
            {"role": "assistant", "content": ann.model_dump_json()},
        ],
    )


def _privileged_hash(spec: str | None) -> str:
    return hashlib.sha256(spec.encode()).hexdigest()[:12] if spec else ""


def _record(
    store: RunStore,
    design: Design,
    table: EntityTable,
    uh: str,
    cfg: RunConfig,
    k_index: int,
    round_: int,
    out: Outcome,
    spec: str | None,
) -> RunRecord:
    rec = RunRecord(
        design={
            "name": design.name,
            "source_hash": design.source_hash(),
            "files": [str(f) for f in design.files],
        },
        module=table.module,
        unit_hash=uh,
        frontend={"tool": "pyslang", "version": SLANG_VERSION, "entities_version": "entities-v1"},
        request={
            "prompt_version": PROMPT_VERSION,
            "taxonomy_version": TAXONOMY_VERSION,
            "model": cfg.teacher.model,
            "effort": cfg.teacher.effort,
            "level": ANN_LEVEL.value,
            "k_index": k_index,
            "round": round_,
            "attempts": out.attempts,
            "privileged": _privileged_hash(spec),
        },
        messages=out.transcript,
        response={
            "raw": out.raw,
            "parsed": out.annotation.model_dump(mode="json") if out.annotation else None,
            "stop_reason": out.stop_reason,
        },
        usage=out.usage,
        validation=out.report.as_dict(),
        source="teacher",
    )
    return store.append(rec)


def annotate_design(
    files: list[str] | None = None,
    *,
    top: str | None = None,
    filelist: str | None = None,
    include_dirs: list[str] | None = None,
    defines: list[str] | None = None,
    cfg: RunConfig | None = None,
    store: RunStore | None = None,
    teacher: Teacher | None = None,
    out_dir: str | Path | None = None,
    name: str | None = None,
    spec: str | None = None,
) -> DesignRun:
    """`spec`: optional natural-language design spec, given to the teacher only (privileged)."""
    cfg = cfg or RunConfig()
    log: list[str] = []
    design = elaborate(
        files, filelist=filelist, include_dirs=include_dirs, defines=defines, top=top, name=name
    )
    if design.errors:
        log.append(f"elaboration errors: {design.errors[:5]}")
    graph = build_graph(design)
    tables = build_entity_tables(graph)
    top_defs = [graph.instances[p].module for p in graph.tops]
    results: dict[str, ModuleResult] = {}
    summaries: dict[str, ModuleResult] = {}  # round-0 results used for parents' CHILD SUMMARIES
    dry: list[dict] = []
    plan: list[dict] = []
    pending: set[str] = set()

    if cfg.mode in ("teacher", "plan"):
        store = store or RunStore()
    if cfg.mode == "teacher" and not cfg.store_only:
        teacher = teacher or Teacher(cfg.teacher)

    for t in tables:
        trivial = is_trivial(t) and not cfg.force_api_for_trivial
        if cfg.mode == "heuristic" or trivial:
            results[t.module] = summaries[t.module] = _heur(
                t, "heuristic: trivial" if trivial else "heuristic: mode"
            )
            log.append(f"{t.module}: heuristic ({'trivial' if trivial else 'mode'})")
            continue

        if cfg.mode == "plan" and any(d in pending for d in t.children.values()):
            pending.add(t.module)
            log.append(f"{t.module}: waiting for children")
            continue
        um = user_message(t, ANN_LEVEL, summaries)
        uh = unit_hash(um + _privileged_hash(spec), cfg.teacher.model, cfg.teacher.effort)
        if cfg.mode == "dry-run":
            dry.append(
                {
                    "module": t.module,
                    "unit_hash": uh,
                    "system": SYSTEM_PROMPT,
                    "user": um,
                    "privileged": privileged_block(spec, t.module, top_defs) if spec else None,
                }
            )
            results[t.module] = summaries[t.module] = _heur(t, "dry-run placeholder")
            continue
        if cfg.mode == "plan":
            missing = [j for j in range(cfg.k) if store.lookup(uh, j, round_=0) is None]
            if missing:
                for j in missing:
                    plan.append(
                        {
                            "custom_id": f"{uh}-k{j}",
                            "unit_hash": uh,
                            "k_index": j,
                            "module": t.module,
                            "user": um,
                            "privileged": privileged_block(spec, t.module, top_defs)
                            if spec
                            else None,
                            "privileged_hash": _privileged_hash(spec),
                            "design": {
                                "name": design.name,
                                "source_hash": design.source_hash(),
                                "files": [str(f) for f in design.files],
                            },
                            "table": t.model().model_dump(mode="json"),
                        }
                    )
                pending.add(t.module)
                log.append(f"{t.module}: planned k={missing}")
                continue
            recs = [store.lookup(uh, j, round_=0) for j in range(cfg.k)]
            samples = [parse_annotation(json.dumps(r.response["parsed"]))[0] for r in recs]
            rep_ann, voted = vote(samples)
            results[t.module] = summaries[t.module] = _result_from(
                t, rep_ann, voted, "teacher", [r.run_id for r in recs], []
            )
            log.append(f"{t.module}: done in store")
            continue

        samples: list[ModuleAnnotation] = []
        sample_k: list[int] = []  # k index of each entry in `samples`
        outcome_k: dict[int, Outcome] = {}
        run_ids: list[str] = []
        for j in range(cfg.k):
            cached = store.lookup(uh, j, round_=0)
            if cached is not None:
                a, _ = parse_annotation(json.dumps(cached.response["parsed"]))
                samples.append(a)
                sample_k.append(j)
                run_ids.append(cached.run_id)
                log.append(f"{t.module}: k{j} reused {cached.run_id}")
                continue
            if cfg.store_only:
                log.append(f"{t.module}: k{j} missing in store (store_only)")
                continue
            if cfg.budget_usd is not None and store.spent_usd() >= cfg.budget_usd:
                raise BudgetExceeded(
                    f"spent ${store.spent_usd():.2f} >= budget ${cfg.budget_usd:.2f}"
                )
            out = teacher.annotate(
                t,
                um,
                ANN_LEVEL,
                privileged=privileged_block(spec, t.module, top_defs) if spec else None,
            )
            rec = _record(store, design, t, uh, cfg, j, 0, out, spec)
            run_ids.append(rec.run_id)
            outcome_k[j] = out
            if out.annotation is not None and out.report.ok:
                samples.append(out.annotation)
                sample_k.append(j)
            log.append(
                f"{t.module}: k{j} attempts={out.attempts} ok={out.report.ok} "
                f"${out.usage.get('usd_est', 0):.4f}"
            )

        if not samples:
            results[t.module] = summaries[t.module] = _heur(
                t, "teacher result missing; heuristic fallback", run_ids
            )
            continue

        rep_ann, voted = vote(samples)
        summaries[t.module] = _result_from(
            t, rep_ann, voted, "teacher", run_ids, []
        )  # round-0 summary for parents

        # ---- multi-pass audit (passes > 1) / legacy refine (passes == 1):
        # later rounds of each sample
        if cfg.use_round == "final":
            for idx, kk in enumerate(sample_k):
                last = store.lookup(
                    uh, kk
                )  # newest successful round (session annotators or earlier runs)
                if last is not None and last.request.get("round", 0) > 0:
                    a, _ = parse_annotation(json.dumps(last.response["parsed"]))
                    if a is not None:
                        samples[idx] = a
                        run_ids.append(last.run_id)
            max_round = cfg.passes - 1 if cfg.passes > 1 else (1 if cfg.refine else 0)
            if not cfg.store_only and max_round > 0:
                for idx, kk in enumerate(sample_k):
                    have = store.lookup(uh, kk)
                    done = have.request.get("round", 0) if have else 0
                    if done >= max_round:
                        continue
                    conv = outcome_k.get(kk) or _rebuild(um, samples[idx], t, spec, top_defs)
                    prev = samples[idx]
                    for rnd in range(done + 1, max_round + 1):
                        findings = module_findings(graph, t, prev)
                        if cfg.passes <= 1 and not findings:
                            break  # legacy refine runs only when the checks found something
                        msg = (
                            audit_message(rnd + 1, findings)
                            if cfg.passes > 1
                            else refine_message(findings)
                        )
                        out = teacher.continue_with(conv, t, msg, ANN_LEVEL)
                        rec = _record(store, design, t, uh, cfg, kk, rnd, out, spec)
                        run_ids.append(rec.run_id)
                        if out.annotation is None or not out.report.ok:
                            break
                        changed = _sig(out.annotation) != _sig(prev)
                        prev = out.annotation
                        log.append(
                            f"{t.module}: k{kk} pass {rnd + 1} "
                            f"{'changed' if changed else 'converged'}"
                        )
                        if not changed:
                            break
                    samples[idx] = prev
            rep_ann, voted = vote(samples)
        warnings = validate(
            rep_ann.model_copy(update={"anchors": list(voted)}), t, ANN_LEVEL
        ).warnings
        if len(samples) > 1:
            warnings.append(f"agreement={agreement(samples)}")
        results[t.module] = _result_from(t, rep_ann, voted, "teacher", run_ids, warnings)

    tb = {t.module: t for t in tables}
    attach_scores(graph, tb, results)  # after annotation: never part of a prompt or cache key
    c = cfg.controls
    views = {m: apply_view(r, c, tb.get(m)) for m, r in results.items()}
    region = region_for(graph, tb, results, c)
    fsms = []
    if "fsm" in cfg.targets:
        from .frontend.fsm_hybrid import extract_fsms_hybrid as extract_fsms
        from .taxonomy import Role

        # also extract registers the teacher labeled FSM_STATE that the frontend did not flag
        extra = {
            m: {a.id for a in r.anchors if a.role == Role.FSM_STATE} for m, r in results.items()
        }
        fsms = extract_fsms(design, graph, tables, extra)
        log.append(f"fsm: {len(fsms)} state machine(s) extracted")
    timing = None
    if "timing" in cfg.targets:
        timing = {
            "status": "not implemented yet "
            "(planned: formal cover traces per handshake interface -> WaveDrom)",
            "interfaces": [
                {
                    "module": m,
                    "name": i.name,
                    "protocol": i.protocol.value,
                    "direction": i.direction.value,
                    "members": [tb[m].by_id()[x].name for x in i.member_ids if x in tb[m].by_id()],
                }
                for m, r in results.items()
                for i in r.interfaces
                if i.protocol.value in ("VALID_READY", "REQ_ACK", "MEMORY_BUS", "STREAM", "SERIAL")
            ],
        }
    run = DesignRun(
        design=design,
        graph=graph,
        tables=tables,
        results_full=results,
        results=views,
        region=region,
        log=log,
        controls=c,
        plan=plan,
        fsms=fsms,
        timing=timing,
        targets=cfg.targets,
    )
    if out_dir:
        write_outputs(run, Path(out_dir), dry)
    return run


def write_outputs(run: DesignRun, out: Path, dry: list[dict] | None = None) -> None:
    d = out / run.design.name
    (d / "entities").mkdir(parents=True, exist_ok=True)
    for t in run.tables:
        (d / "entities" / f"{t.module}.json").write_text(
            t.model().model_dump_json(indent=2), encoding="utf-8"
        )
    (d / "graph.json").write_text(json.dumps(run.graph.to_json(), indent=1), encoding="utf-8")
    full = AnchorsFile(design=run.design.name, tops=run.graph.tops, modules=run.results_full)
    (d / "anchors_full.json").write_text(full.model_dump_json(indent=2), encoding="utf-8")
    view = AnchorsFile(design=run.design.name, tops=run.graph.tops, modules=run.results)
    vj = json.loads(view.model_dump_json())
    vj["controls"] = run.controls.describe()
    (d / "anchors.json").write_text(json.dumps(vj, indent=2), encoding="utf-8")
    (d / "region.json").write_text(
        json.dumps(run.region.to_json(run.graph), indent=1), encoding="utf-8"
    )
    (d / "log.txt").write_text("\n".join(run.log), encoding="utf-8")
    if "fsm" in run.targets:
        (d / "fsm").mkdir(exist_ok=True)
        (d / "fsm.json").write_text(
            json.dumps([f.to_json() for f in run.fsms], indent=1), encoding="utf-8"
        )
        for f in run.fsms:
            stem = f"{f.module}.{f.state}"
            (d / "fsm" / f"{stem}.mmd").write_text(f.mermaid(), encoding="utf-8")
            (d / "fsm" / f"{stem}.dot").write_text(f.dot(), encoding="utf-8")
    if run.timing is not None:
        (d / "timing.json").write_text(json.dumps(run.timing, indent=1), encoding="utf-8")
    if dry:
        (d / "requests").mkdir(exist_ok=True)
        for r in dry:
            (d / "requests" / f"{r['module']}.json").write_text(
                json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
            )


def ingest_batch(
    store: RunStore, plan: list[dict], batch_results: dict[str, dict], cfg: RunConfig
) -> dict:
    """Validate batch / session outputs against the planned entity tables and append them to
    the store."""

    stats = {"ok": 0, "invalid": 0, "errored": 0, "errors": {}}
    for p in plan:
        rr = batch_results.get(p["custom_id"])
        if rr is None:
            stats["errored"] += 1
            continue
        for r in rr if isinstance(rr, list) else [rr]:
            _ingest_one(store, p, r, cfg, stats)
    return stats


def _ingest_one(store, p, r, cfg, stats):
    from .schema import EntityTableModel
    from .validate import Report

    if True:
        if "error" in r:
            stats["errored"] += 1
            return
        tm = EntityTableModel.model_validate(p["table"])
        t = EntityTable(
            design=tm.design,
            module=tm.module,
            canonical_instance=tm.canonical_instance,
            file=tm.file,
            line_start=tm.line_start,
            line_end=tm.line_end,
            rows=tm.rows,
        )
        if r.get("stop_reason") in ("refusal", "max_tokens"):
            ann, err = None, r.get("stop_reason")
        else:
            ann, err = parse_annotation(r["text"])
        rep = Report(errors=[err]) if err else validate(ann, t, ANN_LEVEL)
        rec = RunRecord(
            design=p["design"],
            module=p["module"],
            unit_hash=p["unit_hash"],
            frontend={
                "tool": "pyslang",
                "version": SLANG_VERSION,
                "entities_version": "entities-v1",
            },
            request={
                "prompt_version": PROMPT_VERSION,
                "taxonomy_version": TAXONOMY_VERSION,
                "model": cfg.teacher.model,
                "effort": cfg.teacher.effort,
                "level": ANN_LEVEL.value,
                "k_index": p.get("k_index", 0),
                "round": r.get("round", 0),
                "attempts": 1,
                "batch": r.get("batch", True),
                "privileged": p.get("privileged_hash", ""),
            },
            messages=[
                {"role": "user", "content": p["user"]},
                {"role": "assistant", "content": r["text"]},
            ],
            response={
                "raw": r["text"],
                "parsed": ann.model_dump(mode="json") if ann else None,
                "stop_reason": r.get("stop_reason", ""),
            },
            usage=r.get("usage", {}),
            validation=rep.as_dict(),
            source="teacher",
        )
        store.append(rec)
        if rep.ok:
            stats["ok"] += 1
        else:
            stats["invalid"] += 1
            stats["errors"][f"{p['custom_id']}@r{r.get('round', 0)}"] = rep.errors
