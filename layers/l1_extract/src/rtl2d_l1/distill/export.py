"""Run Store -> SFT dataset (SPEC §8 filter, §9 I/O contract).

Each sample is chat-format: system (frozen prompt) + user (module unit) -> assistant (final JSON).
Only the final, validated annotation is kept (no thinking, no retries) so the student
learns exactly the teacher's I/O contract.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from ..llm.prompt import SYSTEM_PROMPT
from ..store import RunRecord, RunStore
from ..versions import TAXONOMY_VERSION


def _final_by_unit(store: RunStore) -> dict[str, list[RunRecord]]:
    """unit_hash -> best record per k_index (highest round that parsed without errors)."""
    best: dict[tuple[str, int], RunRecord] = {}
    for r in store.iter_records():
        if r.response.get("parsed") is None or r.validation.get("errors"):
            continue
        key = (r.unit_hash, r.request.get("k_index", 0))
        cur = best.get(key)
        if cur is None or r.request.get("round", 0) >= cur.request.get("round", 0):
            best[key] = r
    out: dict[str, list[RunRecord]] = defaultdict(list)
    for (uh, _), r in best.items():
        out[uh].append(r)
    return out


def export_sft(
    store: RunStore,
    out_path: str | Path,
    *,
    min_confidence: float = 0.67,
    taxonomy_version: str = TAXONOMY_VERSION,
    include_human: bool = True,
    max_per_rtl: int | None = 2,
) -> dict:
    """`max_per_rtl`: keep at most this many units whose module RTL text is identical (the same
    module elaborated with different parameters differs only in widths in the entity table)."""
    units = _final_by_unit(store)
    n_written = n_skipped = n_dup = 0
    per_rtl: dict[str, int] = defaultdict(int)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for uh, recs in units.items():
            recs = [r for r in recs if r.request.get("taxonomy_version") == taxonomy_version]
            if not recs:
                n_skipped += 1
                continue
            human = [r for r in recs if r.source == "human" and include_human]
            if human:
                chosen, conf = human[-1], 1.0
            else:
                # agreement of this sample's anchor set with the others = soft confidence
                k = len(recs)
                ids = [{a["id"] for a in r.response["parsed"]["anchors"]} for r in recs]
                if k == 1:
                    chosen, conf = recs[0], 1.0
                else:
                    votes: dict[str, int] = defaultdict(int)
                    for s in ids:
                        for x in s:
                            votes[x] += 1
                    keep = {x for x, v in votes.items() if v / k >= 0.5}
                    scores = [len(s & keep) / max(1, len(s | keep)) for s in ids]
                    i = max(range(k), key=lambda j: scores[j])
                    chosen, conf = recs[i], scores[i]
            if conf < min_confidence:
                n_skipped += 1
                continue
            user = next((m["content"] for m in chosen.messages if m["role"] == "user"), None)
            if user is None:
                n_skipped += 1
                continue
            if max_per_rtl is not None:
                rtl = user.split("RTL (line-numbered):", 1)[-1]
                key = hashlib.sha1((chosen.module + "\n" + rtl).encode()).hexdigest()
                if per_rtl[key] >= max_per_rtl:
                    n_dup += 1
                    continue
                per_rtl[key] += 1
            sample = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                    {
                        "role": "assistant",
                        "content": json.dumps(chosen.response["parsed"], ensure_ascii=False),
                    },
                ],
                "meta": {
                    "unit_hash": uh,
                    "run_id": chosen.run_id,
                    "module": chosen.module,
                    "design": chosen.design.get("name"),
                    "confidence": round(conf, 3),
                    "source": chosen.source,
                },
            }
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
            n_written += 1
    return {
        "written": n_written,
        "skipped": n_skipped,
        "duplicates_dropped": n_dup,
        "path": str(out_path),
    }


def assemble_sft(
    teacher_path: str | Path,
    augment_paths: list[str | Path],
    out_dir: str | Path,
    *,
    eval_frac: float = 0.08,
) -> dict:
    """Merge teacher samples and rename-augmented samples into train/eval files.

    The split is by ORIGINAL MODULE (all parameter variants and all renamed copies of a module
    land on the same side), so the eval set measures generalization to unseen modules rather
    than recall of a renamed copy."""
    teacher = [json.loads(x) for x in Path(teacher_path).read_text(encoding="utf-8").splitlines()]
    group_of_unit = {s["meta"]["unit_hash"]: s["meta"]["module"] for s in teacher}
    rows = [(s["meta"]["module"], s) for s in teacher]
    n_aug_orphan = 0
    for p in augment_paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            s = json.loads(line)
            g = group_of_unit.get(s["meta"].get("orig_unit_hash"))
            if g is None:  # its teacher sample was dropped (duplicate / low confidence)
                n_aug_orphan += 1
                continue
            rows.append((g, s))

    def is_eval(group: str) -> bool:
        h = int(hashlib.sha1(group.encode()).hexdigest()[:8], 16)
        return h / 0xFFFFFFFF < eval_frac

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stats = {"train": 0, "eval": 0, "train_groups": set(), "eval_groups": set(), "augment": 0}
    with (
        (out / "train.jsonl").open("w", encoding="utf-8") as ft,
        (out / "eval.jsonl").open("w", encoding="utf-8") as fe,
    ):
        for g, s in rows:
            side = "eval" if is_eval(g) else "train"
            (fe if side == "eval" else ft).write(json.dumps(s, ensure_ascii=False) + "\n")
            stats[side] += 1
            stats[f"{side}_groups"].add(g)
            stats["augment"] += s["meta"].get("source") == "augment-rename"
    stats = {k: (len(v) if isinstance(v, set) else v) for k, v in stats.items()} | {
        "augment_without_teacher_sample": n_aug_orphan,
        "path": str(out),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    return stats
