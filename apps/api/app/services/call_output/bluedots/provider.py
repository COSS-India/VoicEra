"""Blue Dots ``call_output`` provider: KKB Slim output from AI DPG logs + transcript."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.services.call_output.base import CallOutputNotReady, CallOutputResult
from app.services.call_output.bluedots import schema
from app.services.call_output.bluedots.llm import OutputParseError, extractor_from_settings
from app.services.call_output.bluedots.loki import fetch_call_lines
from app.services.call_output.bluedots.signals import CallSignals, extract
from app.services.call_transcript_service import try_load_turns

logger = logging.getLogger(__name__)

_SPOKEN = re.compile(r"\w", re.UNICODE)


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _load_transcript(call: dict[str, Any]) -> list[dict[str, Any]]:
    return try_load_turns(call) or []


def caller_turns(turns: list[dict[str, Any]]) -> int:
    return sum(
        1 for turn in turns
        if turn.get("speaker") != "agent" and _SPOKEN.search(str(turn.get("text") or ""))
    )


def call_facts(call: dict[str, Any], signals: CallSignals, turns: list[dict[str, Any]]) -> schema.CallFacts:
    facts = schema.CallFacts(
        seeker_name=schema.seeker_name_from(call),
        input_location=schema.input_location_from(call),
        caller_turns=caller_turns(turns),
        phases=signals.phases,
    )
    for tool_call in signals.tools:
        facts.calls[tool_call.tool] = facts.calls.get(tool_call.tool, 0) + 1
        bucket = facts.successes if tool_call.ok else facts.failures
        bucket[tool_call.tool] = bucket.get(tool_call.tool, 0) + 1
    return facts


def _tool_for_model(call: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"tool": call.tool, "status": "success" if call.ok else "failure"}
    if call.error:
        entry["error"] = call.error
    if call.arguments:
        entry["arguments"] = call.arguments
    if call.result:
        entry["result"] = call.result  # as AI DPG logged it, at most 2,000 characters
    return entry


JOB_LISTS = ("jobs_recommended", "jobs_applied", "jobs_failed_to_apply")


def keep_known_job_ids(output: dict[str, Any], signals: CallSignals) -> dict[str, str]:
    """Reset any job_id no tool call mentions to "NA" (the model must not invent one)."""
    seen = " ".join(
        json.dumps(t.arguments or {}, ensure_ascii=False) + " " + (t.result or "") for t in signals.tools
    )
    sources: dict[str, str] = {}
    for name in JOB_LISTS:
        for job in output.get(name) or []:
            job_id = str(job.get("job_id") or "NA")
            if job_id != "NA" and job_id not in seen:
                job["job_id"] = "NA"
                sources[name] = "job_id not in any tool call: reset to NA"
    return sources


def unanswered_output(call: dict[str, Any]) -> dict[str, Any]:
    return schema.unanswered_output(schema.seeker_name_from(call))


class BlueDotsCallOutputProvider:
    name = "bluedots"

    def unanswered_output(self, call: dict[str, Any]) -> dict[str, Any]:
        return unanswered_output(call)

    async def compute(
        self,
        call: dict[str, Any],
        agent: dict[str, Any],
        *,
        client: httpx.AsyncClient,
        now: datetime | None = None,
    ) -> CallOutputResult:
        base_url = (settings.BLUEDOTS_LOKI_URL or "").strip()
        if not base_url:
            raise RuntimeError("BLUEDOTS_LOKI_URL is not set")
        extractor = extractor_from_settings()
        current = now or datetime.now(timezone.utc)
        call_id = str(call["call_id"])
        started = _as_utc(call.get("start_time_utc")) or _as_utc(call.get("created_at")) or current
        ended = _as_utc(call.get("end_time_utc")) or current

        lines = await fetch_call_lines(
            client,
            base_url=base_url,
            selector=settings.BLUEDOTS_LOKI_SELECTOR,
            call_id=call_id,
            start=started - timedelta(minutes=2),
            end=min(current, ended + timedelta(minutes=10)),
            timeout=settings.BLUEDOTS_LOKI_TIMEOUT_SECONDS,
        )
        signals = extract(lines)
        grace = timedelta(seconds=settings.CALL_OUTPUT_LOG_GRACE_SECONDS)
        if signals.empty and current < ended + grace:
            raise CallOutputNotReady("no Agent Core log lines for this call yet")

        turns = _load_transcript(call)
        facts = call_facts(call, signals, turns)
        meta: dict[str, Any] = {
            **signals.to_dict(),
            "schema": schema.SCHEMA,
            "spec": schema.SPEC_SOURCE,
            "transcript_turns": len(turns),
            "caller_turns": facts.caller_turns,
            "log_lines": len(lines),
            "llm_model": None,
        }

        if not facts.caller_turns:
            output = unanswered_output(call)
            meta["sources"] = {"*": "no caller speech in the transcript"}
            return CallOutputResult(output=output, signals=meta)

        if extractor is None:
            # Retried, then ``failed``; recompute once the settings are in.
            raise RuntimeError("CALL_OUTPUT_LLM_BASE_URL / CALL_OUTPUT_LLM_MODEL are not set")

        inputs = {"seeker_name": facts.seeker_name, "location": facts.input_location}
        tool_calls = [_tool_for_model(t) for t in signals.tools]
        try:
            raw = await extractor.extract(
                client, turns, inputs=inputs, tool_calls=tool_calls, phases=signals.phases
            )
        except (httpx.HTTPError, OutputParseError) as exc:
            raise CallOutputNotReady(f"output model failed: {exc}") from exc

        output, sources = schema.apply_facts(schema.normalise(raw), facts)
        sources.update(keep_known_job_ids(output, signals))
        meta["sources"] = sources
        meta["llm_model"] = extractor.model
        return CallOutputResult(output=output, signals=meta)
