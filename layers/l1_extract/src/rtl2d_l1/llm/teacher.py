"""Teacher client (SPEC §7): Claude Opus 5.5 + structured outputs + retry/refine loop.

Conversations are append-only (assistant content is echoed back unchanged), so
thinking blocks stay valid across the retry/refine turns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ..frontend.entities import EntityTable
from ..schema import ModuleAnnotation, annotation_json_schema
from ..store import usd_estimate
from ..taxonomy import Level
from ..validate import Report, validate
from .prompt import SYSTEM_PROMPT, retry_message

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class TeacherConfig:
    model: str = "claude-opus-5-5"
    effort: str = "high"
    max_tokens: int = 64000
    use_fallbacks: bool = True
    max_retries: int = 2


@dataclass
class Outcome:
    annotation: ModuleAnnotation | None
    report: Report
    transcript: list[dict[str, Any]]  # text-only transcript for the store
    api_messages: list[
        dict[str, Any]
    ]  # exact messages (with thinking blocks) to continue the conversation
    raw: str = ""
    stop_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0


def _system_blocks() -> list[dict]:
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]


def request_params(cfg: TeacherConfig, messages: list[dict]) -> dict:
    """Parameters shared by the sync and batch paths."""
    return {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "system": _system_blocks(),
        "messages": messages,
        "thinking": {"type": "adaptive"},
        "output_config": {
            "effort": cfg.effort,
            "format": {"type": "json_schema", "schema": annotation_json_schema()},
        },
    }


def _usage_dict(u, model: str, batch: bool = False) -> dict:
    if u is None:
        return {}
    d = {
        "input": getattr(u, "input_tokens", 0) or 0,
        "output": getattr(u, "output_tokens", 0) or 0,
        "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "batch": batch,
    }
    d["usd_est"] = usd_estimate(model, d, batch)
    return d


def _add_usage(a: dict, b: dict) -> dict:
    out = dict(a)
    for k in ("input", "output", "cache_read", "cache_write", "usd_est"):
        out[k] = round(out.get(k, 0) + b.get(k, 0), 6)
    out["batch"] = a.get("batch", False) or b.get("batch", False)
    return out


def message_text(msg) -> str:
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def parse_annotation(text: str) -> tuple[ModuleAnnotation | None, str | None]:
    try:
        return ModuleAnnotation.model_validate(json.loads(text)), None
    except (json.JSONDecodeError, ValidationError) as e:
        return None, f"output is not a valid annotation: {str(e)[:300]}"


class Teacher:
    def __init__(self, cfg: TeacherConfig | None = None, client=None):
        self.cfg = cfg or TeacherConfig()
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client

    # ----------------------------------------------------------------- calls
    def _call(self, messages: list[dict]):
        params = request_params(self.cfg, messages)
        extra = {}
        if self.cfg.use_fallbacks:
            extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        with self.client.beta.messages.stream(**params, **extra) as s:
            return s.get_final_message()

    def _turn(self, out: Outcome, table: EntityTable, level: Level) -> None:
        msg = self._call(out.api_messages)
        out.attempts += 1
        out.stop_reason = msg.stop_reason or ""
        out.usage = _add_usage(out.usage, _usage_dict(msg.usage, self.cfg.model))
        # echo assistant content back unchanged (thinking blocks must stay intact)
        out.api_messages.append(
            {"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in msg.content]}
        )
        text = message_text(msg)
        out.raw = text
        out.transcript.append({"role": "assistant", "content": text})
        if msg.stop_reason == "refusal":
            out.annotation = None
            out.report = Report(errors=[f"refusal: {getattr(msg, 'stop_details', None)}"])
            return
        if msg.stop_reason == "max_tokens":
            out.annotation = None
            out.report = Report(errors=["max_tokens reached"])
            return
        ann, err = parse_annotation(text)
        out.annotation = ann
        out.report = Report(errors=[err]) if err else validate(ann, table, level)

    def _push_user(self, out: Outcome, text: str, privileged: str | None = None) -> None:
        out.api_messages.append({"role": "user", "content": text + (privileged or "")})
        out.transcript.append({"role": "user", "content": text})  # student-visible part only

    # ------------------------------------------------------------- workflows
    def annotate(
        self,
        table: EntityTable,
        user_msg: str,
        level: Level = Level.LOW,
        privileged: str | None = None,
    ) -> Outcome:
        out = Outcome(annotation=None, report=Report(), transcript=[], api_messages=[])
        self._push_user(out, user_msg, privileged)
        self._turn(out, table, level)
        retries = 0
        while (
            out.report.errors
            and retries < self.cfg.max_retries
            and out.stop_reason not in ("refusal",)
        ):
            retries += 1
            self._push_user(out, retry_message(out.report.errors))
            self._turn(out, table, level)
        return out

    def continue_with(
        self, out: Outcome, table: EntityTable, text: str, level: Level = Level.MEDIUM
    ) -> Outcome:
        """Append one more user turn (refine round) to an existing conversation."""
        prev = out.annotation, out.report
        self._push_user(out, text)
        self._turn(out, table, level)
        if out.report.errors and prev[0] is not None:
            # refine made it worse: keep the previous valid annotation
            out.annotation, out.report = prev
        return out


# ------------------------------------------------------------------ batches
def build_batch_requests(cfg: TeacherConfig, units: list[tuple[str, str]]) -> list[dict]:
    """units: (custom_id, user_msg). Fallbacks are not supported on the Batch API."""
    return [
        {"custom_id": cid, "params": request_params(cfg, [{"role": "user", "content": um}])}
        for cid, um in units
    ]


def submit_batch(client, cfg: TeacherConfig, units: list[tuple[str, str]]) -> str:
    batch = client.messages.batches.create(requests=build_batch_requests(cfg, units))
    return batch.id


def collect_batch(client, batch_id: str, model: str) -> dict[str, dict]:
    """Return custom_id -> {text, stop_reason, usage, content, error}. Raises if not ended."""
    b = client.messages.batches.retrieve(batch_id)
    if b.processing_status != "ended":
        raise RuntimeError(f"batch {batch_id} is {b.processing_status}")
    out: dict[str, dict] = {}
    for r in client.messages.batches.results(batch_id):
        if r.result.type == "succeeded":
            m = r.result.message
            out[r.custom_id] = {
                "text": message_text(m),
                "stop_reason": m.stop_reason,
                "usage": _usage_dict(m.usage, model, batch=True),
                "content": [blk.model_dump(exclude_none=True) for blk in m.content],
            }
        else:
            out[r.custom_id] = {"error": r.result.type}
    return out
