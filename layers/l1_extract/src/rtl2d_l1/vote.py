"""Self-consistency voting over k annotations (SPEC §7.2)."""

from __future__ import annotations

import math
from collections import Counter

from .schema import ModuleAnnotation, VotedAnchor


def _mode(xs, rank=None):
    """Most common value; ties go to the first sample's value, or to the highest `rank` when
    given."""
    c = Counter(xs)
    top = max(c.values())
    tied = [x for x in xs if c[x] == top]
    if rank is not None:
        return max(tied, key=rank)
    return tied[0]


_IMP_RANK = {"critical": 2, "major": 1, "minor": 0}


def vote(samples: list[ModuleAnnotation]) -> tuple[ModuleAnnotation, list[VotedAnchor]]:
    """Return (representative sample for groups/interfaces/summary, voted anchors)."""
    samples = [s for s in samples if s is not None]
    if not samples:
        return ModuleAnnotation(), []
    k = len(samples)
    need = math.ceil(k / 2)
    by_id: dict[str, list] = {}
    for s in samples:
        for a in s.anchors:
            by_id.setdefault(a.id, []).append(a)
    voted: list[VotedAnchor] = []
    for aid, al in by_id.items():
        if len(al) < need:
            continue
        voted.append(
            VotedAnchor(
                id=aid,
                name=al[0].name,
                role=_mode([a.role for a in al]),
                # ties (typical with k=2) round UP: the HIGH view must not lose a concept one
                # annotator rated critical
                importance=_mode([a.importance for a in al], rank=lambda i: _IMP_RANK[i.value]),
                trace=_mode([a.trace for a in al]),
                why=al[0].why,
                lines=sorted({ln for a in al for ln in a.lines}),  # evidence (union of samples)
                confidence=round(len(al) / k, 3),
            )
        )
    voted.sort(key=lambda a: int(a.id[1:]) if a.id[1:].isdigit() else 0)
    keep = {a.id for a in voted}

    def jacc(s: ModuleAnnotation) -> float:
        ids = {a.id for a in s.anchors}
        return len(ids & keep) / max(1, len(ids | keep))

    rep = max(samples, key=jacc)
    return rep, voted


def agreement(samples: list[ModuleAnnotation]) -> float:
    """Mean pairwise Jaccard of anchor id sets."""
    sets = [{a.id for a in s.anchors} for s in samples if s is not None]
    if len(sets) < 2:
        return 1.0
    vals = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            u = sets[i] | sets[j]
            vals.append(len(sets[i] & sets[j]) / len(u) if u else 1.0)
    return round(sum(vals) / len(vals), 4)
