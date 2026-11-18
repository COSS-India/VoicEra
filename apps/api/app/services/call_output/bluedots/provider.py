"""Blue Dots ``call_output`` provider: Loki signals + transcript -> funnel."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.services.call_output.base import CallOutputNotReady, CallOutputResult
from app.services.call_output.bluedots import funnel
from app.services.call_output.bluedots.llm import judge_from_settings
from app.services.call_output.bluedots.loki import fetch_call_lines
from app.services.call_output.bluedots.signals import extract
from app.services.call_transcript_service import try_load_turns

logger = logging.getLogger(__name__)


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


class BlueDotsCallOutputProvider:
    name = "bluedots"

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

        transcript = _load_transcript(call)
        ask_jobs = funnel.needs_jobs_judgement(signals)
        ask_drop = funnel.needs_drop_judgement(signals)
        judgement = None
        judge = judge_from_settings()
        if judge is not None and transcript and (ask_jobs or ask_drop):
            facts = {
                "phases": signals.phases,
                "tools": [{"tool": t.tool, "ok": t.ok} for t in signals.tools],
            }
            try:
                judgement = await judge.judge(
                    client, transcript, facts=facts, ask_jobs=ask_jobs, ask_drop=ask_drop
                )
            except httpx.HTTPError as exc:
                # Retried by the core: a transient LLM failure should not
                # leave the funnel without a drop reason for good.
                raise CallOutputNotReady(f"transcript judge failed: {exc}") from exc

        output, sources = funnel.build(signals, judgement)
        return CallOutputResult(
            output=output,
            signals={
                **signals.to_dict(),
                "sources": sources,
                "llm_model": judgement.model if judgement else None,
                "transcript_turns": len(transcript),
                "log_lines": len(lines),
            },
        )
