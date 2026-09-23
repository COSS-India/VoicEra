"""Pipeline run lifecycle and call finalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from pipecat.pipeline.worker import PipelineWorker
from pipecat.workers.runner import WorkerRunner

from apps.runtime.services.backend import backend_client
from apps.runtime.services.pipecat.duration_guard import (
    MAX_DURATION_END_REASON,
    DurationGuard,
)
from apps.runtime.services.pipecat.metrics.writer import CallMetricsWriter
from apps.runtime.services.storage.transcript import TranscriptWriter


@dataclass
class SessionContext:
    org_id: str
    call_id: str | None
    session_label: str
    finalize_call: bool
    agent_id: str | None
    sample_rate: int
    transcript_writer: TranscriptWriter | None = None
    metrics_writer: CallMetricsWriter | None = None
    # Layer 3 hard cap (rate-limiting-plan.md). None/0 disables the guard.
    max_duration_seconds: float | None = None


async def finalize_call(
    org_id: str, call_id: str, *, end_reason: str | None = None
) -> None:
    patch: dict[str, Any] = {
        "end_time_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "call_response": "answered",
    }
    if end_reason:
        patch["end_reason"] = end_reason
    try:
        await backend_client.update_call(call_id, org_id, patch)
        await backend_client.notify_campaign_call_status(org_id, call_id, "answered")
    except Exception:
        logger.warning(
            "Failed to finalize call call_id={}",
            call_id,
            exc_info=True,
        )


async def run_with_lifecycle(worker: PipelineWorker, ctx: SessionContext) -> None:
    runner = WorkerRunner(handle_sigint=False)
    logger.info(
        "Starting pipeline agent_id={} {} sample_rate={}",
        ctx.agent_id,
        ctx.session_label,
        ctx.sample_rate,
    )

    guard: DurationGuard | None = None
    if ctx.max_duration_seconds:
        async def _on_max_duration() -> None:
            logger.warning(
                "call.max_duration_reached call_id={} limit={}",
                ctx.call_id,
                ctx.max_duration_seconds,
            )
            # Graceful shutdown: unblocks runner.run()'s wait on
            # _shutdown_event so it returns normally through this function's
            # existing `finally`, rather than tearing the pipeline down
            # mid-frame.
            await runner.end(reason=MAX_DURATION_END_REASON)

        guard = DurationGuard(ctx.max_duration_seconds, _on_max_duration)
        guard.start()

    await runner.add_workers(worker)
    try:
        await runner.run()
    finally:
        if guard is not None:
            guard.cancel()
        if ctx.transcript_writer:
            await ctx.transcript_writer.flush()
        if ctx.metrics_writer:
            await ctx.metrics_writer.flush()
        if ctx.finalize_call and ctx.call_id:
            end_reason = MAX_DURATION_END_REASON if guard and guard.fired else None
            await finalize_call(ctx.org_id, ctx.call_id, end_reason=end_reason)
