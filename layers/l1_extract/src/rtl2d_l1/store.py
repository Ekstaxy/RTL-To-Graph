"""Run Store (SPEC §8): append-only JSONL + SQLite index keyed by work-unit hash.

Every record is a self-contained training sample candidate with full provenance.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .versions import ENTITIES_VERSION, RUNSTORE_VERSION, TAXONOMY_VERSION

# USD per 1M tokens (2026-09 list prices). Cache write = 1.25x input (5-minute TTL).
PRICES = {
    "claude-opus-5-5": {"in": 4.00, "out": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00, "cache_read": 0.10, "cache_write": 1.25},
}


def usd_estimate(model: str, usage: dict, batch: bool = False) -> float:
    p = PRICES.get(model)
    if not p:
        return 0.0
    cost = (
        usage.get("input", 0) * p["in"]
        + usage.get("output", 0) * p["out"]
        + usage.get("cache_read", 0) * p["cache_read"]
        + usage.get("cache_write", 0) * p["cache_write"]
    ) / 1e6
    return round(cost * (0.5 if batch else 1.0), 6)


class RunRecord(BaseModel):
    version: str = RUNSTORE_VERSION
    run_id: str = Field(
        default_factory=lambda: (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]
        )
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    design: dict[str, Any]
    module: str
    unit_hash: str
    frontend: dict[str, Any] = Field(
        default_factory=lambda: {"tool": "pyslang", "entities_version": ENTITIES_VERSION}
    )
    request: dict[
        str, Any
    ]  # prompt_version, taxonomy_version, model, effort, level, k_index, round
    messages: list[dict[str, Any]] = Field(
        default_factory=list
    )  # text transcript (system omitted; it is versioned)
    response: dict[str, Any] = Field(default_factory=dict)  # raw, parsed, stop_reason
    usage: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    source: str = "teacher"
    stage2_feedback: dict[str, Any] | None = None
    human: dict[str, Any] | None = None


class RunStore:
    def __init__(self, root: str | Path = "runs/store"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.jsonl = self.root / "runs.jsonl"
        self.db = sqlite3.connect(self.root / "index.sqlite")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, unit_hash TEXT, "
            "module TEXT, design TEXT,"
            " k_index INT, round INT, source TEXT, ok INT, usd REAL, taxonomy TEXT, offset INT)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_unit ON runs(unit_hash, k_index, round)")
        self.db.commit()

    def append(self, rec: RunRecord) -> RunRecord:
        line = rec.model_dump_json()
        with self.jsonl.open("ab") as f:
            off = f.tell()
            f.write(line.encode("utf-8") + b"\n")
        self.db.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                rec.run_id,
                rec.unit_hash,
                rec.module,
                rec.design.get("name", ""),
                rec.request.get("k_index", 0),
                rec.request.get("round", 0),
                rec.source,
                int(not rec.validation.get("errors"))
                if rec.response.get("parsed") is not None
                else 0,
                rec.usage.get("usd_est", 0.0),
                rec.request.get("taxonomy_version", TAXONOMY_VERSION),
                off,
            ),
        )
        self.db.commit()
        return rec

    def _read_at(self, offset: int) -> RunRecord:
        with self.jsonl.open("rb") as f:
            f.seek(offset)
            return RunRecord.model_validate_json(f.readline())

    def lookup(self, unit_hash: str, k_index: int, round_: int | None = None) -> RunRecord | None:
        """Latest successful record for this unit/sample (highest round unless given)."""
        q = "SELECT offset FROM runs WHERE unit_hash=? AND k_index=? AND ok=1"
        args: list = [unit_hash, k_index]
        if round_ is not None:
            q += " AND round=?"
            args.append(round_)
        q += " ORDER BY round DESC, rowid DESC LIMIT 1"
        row = self.db.execute(q, args).fetchone()
        return self._read_at(row[0]) if row else None

    def iter_records(self):
        if not self.jsonl.exists():
            return
        with self.jsonl.open("rb") as f:
            for line in f:
                if line.strip():
                    yield RunRecord.model_validate_json(line)

    def spent_usd(self) -> float:
        row = self.db.execute("SELECT COALESCE(SUM(usd),0) FROM runs").fetchone()
        return float(row[0])

    def set_feedback(self, run_id: str, feedback: dict) -> None:
        """Feedback is appended as a new 'feedback' line (store stays append-only)."""
        with (self.root / "feedback.jsonl").open("a", encoding="utf-8") as f:
            f.write(
                json.dumps({"run_id": run_id, "stage2_feedback": feedback}, ensure_ascii=False)
                + "\n"
            )
