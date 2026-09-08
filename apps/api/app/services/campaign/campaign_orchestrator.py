"""Campaign orchestrator — event-driven batch scheduling and completion detection."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis

from app.config import settings
from app.constants.campaign import CAMPAIGN_EVENTS_CHANNEL
from app.services.campaign import campaign_repository as repo
from app.services.campaign.campaign_event_protocol import (
    BatchCompletedEvent,
    BatchFailedEvent,
    CircuitBreakerTrippedEvent,
    RetryNeededEvent,
    SyncCompletedEvent,
    parse_campaign_event,
)
from app.services.campaign.campaign_event_publisher import CampaignEventPublisher
from app.services.campaign.circuit_breaker import circuit_breaker
from app.tasks.arq import enqueue_job
from app.tasks.function_names import FunctionNames

logger = logging.getLogger(__name__)


class CampaignOrchestrator:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self.redis = redis_client
        self.publisher = CampaignEventPublisher(redis_client)
        self.completion_check_interval = 60
        self.completion_timeout = 3600
        self._processing_locks: dict[str, datetime] = {}
        self._last_activity: dict[str, datetime] = {}
        self._batch_in_progress: dict[str, datetime] = {}
        self._running = False
        self._pubsub = None

    async def run(self) -> None:
        self._running = True
        logger.info("Campaign Orchestrator starting...")
        try:
            event_task = asyncio.create_task(self._listen_for_events())
            completion_task = asyncio.create_task(self._monitor_completion())
            await asyncio.gather(event_task, completion_task)
        finally:
            await self.shutdown()

    async def _listen_for_events(self) -> None:
        self._pubsub = self.redis.pubsub()
        await self._pubsub.subscribe(CAMPAIGN_EVENTS_CHANNEL)
        async for message in self._pubsub.listen():
            if not self._running:
                break
            if message["type"] != "message":
                continue
            event = parse_campaign_event(message["data"])
            if event:
                await self._handle_event(event)

    async def _handle_event(self, event) -> None:
        campaign_id = getattr(event, "campaign_id", "") or ""
        if not campaign_id:
            return
        if isinstance(event, RetryNeededEvent):
            await self._handle_retry_event(event)
        elif isinstance(event, BatchCompletedEvent):
            self._batch_in_progress.pop(campaign_id, None)
            campaign = await asyncio.to_thread(repo.get_campaign_by_id, campaign_id)
            if not campaign or campaign.get("state") != "running":
                self._clear_campaign_state(campaign_id)
                return
            await self._schedule_next_batch(campaign_id)
            self._last_activity[campaign_id] = datetime.now(timezone.utc)
        elif isinstance(event, BatchFailedEvent):
            self._batch_in_progress.pop(campaign_id, None)
            self._last_activity[campaign_id] = datetime.now(timezone.utc)
        elif isinstance(event, SyncCompletedEvent):
            await self._schedule_next_batch(campaign_id)
            self._last_activity[campaign_id] = datetime.now(timezone.utc)
        elif isinstance(event, CircuitBreakerTrippedEvent):
            self._clear_campaign_state(campaign_id)

    async def _handle_retry_event(self, event: RetryNeededEvent) -> None:
        campaign_id = event.campaign_id
        if not campaign_id:
            return
        campaign = await asyncio.to_thread(repo.get_campaign_by_id, campaign_id)
        if not campaign:
            return
        retry_config = campaign.get("retry_config") or {}
        if not retry_config.get("enabled", True):
            return
        reason = event.reason
        if reason == "busy" and not retry_config.get("retry_on_busy", True):
            return
        if reason == "no_answer" and not retry_config.get("retry_on_no_answer", True):
            return
        if reason == "voicemail" and not retry_config.get("retry_on_voicemail", False):
            return
        queued_run = await asyncio.to_thread(
            repo.get_queued_run_by_id, event.queued_run_id
        )
        if not queued_run:
            return
        max_retries = int(retry_config.get("max_retries", 1))
        if int(queued_run.get("retry_count") or 0) >= max_retries:
            await asyncio.to_thread(
                repo.update_campaign,
                campaign_id,
                failed_rows=int(campaign.get("failed_rows") or 0) + 1,
            )
            return
        delay = int(retry_config.get("retry_delay_seconds", 120))
        retry_context = {
            **(queued_run.get("context_variables") or {}),
            "is_retry": True,
            "retry_attempt": int(queued_run.get("retry_count") or 0) + 1,
            "retry_reason": reason,
        }
        scheduled = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
        retry_count = int(queued_run.get("retry_count") or 0) + 1
        await asyncio.to_thread(
            repo.create_queued_run,
            campaign_id=campaign_id,
            source_uuid=f"{queued_run['source_uuid']}_retry_{retry_count}",
            context_variables=retry_context,
            state="queued",
            retry_count=retry_count,
            parent_queued_run_id=queued_run["queued_run_id"],
            scheduled_for=scheduled,
            retry_reason=reason,
        )
        self._last_activity[campaign_id] = datetime.now(timezone.utc)

    def _is_within_schedule(self, campaign: dict) -> bool:
        metadata = campaign.get("orchestrator_metadata") or {}
        schedule_config = metadata.get("schedule_config")
        if not schedule_config or not schedule_config.get("enabled", False):
            return True
        slots = schedule_config.get("slots") or []
        if not slots:
            return True
        try:
            tz = ZoneInfo(schedule_config.get("timezone", "UTC"))
        except Exception:
            return True
        now = datetime.now(tz)
        current_day = now.weekday()
        current_time = now.strftime("%H:%M")
        for slot in slots:
            if slot.get("day_of_week") == current_day:
                start = slot.get("start_time", "")
                end = slot.get("end_time", "")
                if start <= current_time < end:
                    return True
        return False

    async def _schedule_next_batch(self, campaign_id: str) -> None:
        if campaign_id in self._processing_locks:
            if (datetime.now(timezone.utc) - self._processing_locks[campaign_id]).total_seconds() < 5:
                return
        self._processing_locks[campaign_id] = datetime.now(timezone.utc)
        try:
            campaign = await asyncio.to_thread(repo.get_campaign_by_id, campaign_id)
            if not campaign or campaign.get("state") not in ("running", "syncing"):
                return
            if not self._is_within_schedule(campaign):
                return
            metadata = campaign.get("orchestrator_metadata") or {}
            cb_config = metadata.get("circuit_breaker")
            is_open, stats = await circuit_breaker.is_circuit_open(
                campaign_id, config=cb_config
            )
            if is_open and stats:
                await asyncio.to_thread(repo.update_campaign, campaign_id, state="paused")
                await self.publisher.publish_circuit_breaker_tripped(
                    campaign_id=campaign_id,
                    failure_rate=stats["failure_rate"],
                    failure_count=stats["failure_count"],
                    success_count=stats["success_count"],
                    threshold=stats["threshold"],
                    window_seconds=stats["window_seconds"],
                )
                self._clear_campaign_state(campaign_id)
                return
            if await self._has_pending_work(campaign_id):
                batch_size = settings.CAMPAIGN_BATCH_SIZE
                await enqueue_job(
                    FunctionNames.PROCESS_CAMPAIGN_BATCH,
                    campaign_id,
                    batch_size,
                )
                self._batch_in_progress[campaign_id] = datetime.now(timezone.utc)
                await asyncio.to_thread(
                    repo.update_campaign,
                    campaign_id,
                    last_batch_scheduled_at=datetime.now(timezone.utc).isoformat(),
                    last_activity_at=datetime.now(timezone.utc).isoformat(),
                )
        finally:
            asyncio.create_task(self._release_lock_after_delay(campaign_id, 5))

    async def _release_lock_after_delay(self, campaign_id: str, delay: int) -> None:
        await asyncio.sleep(delay)
        self._processing_locks.pop(campaign_id, None)

    def _clear_campaign_state(self, campaign_id: str) -> None:
        self._last_activity.pop(campaign_id, None)
        self._processing_locks.pop(campaign_id, None)
        self._batch_in_progress.pop(campaign_id, None)

    async def _has_pending_work(self, campaign_id: str) -> bool:
        before = datetime.now(timezone.utc).isoformat()
        queued = await asyncio.to_thread(
            repo.count_pending_queued_runs, campaign_id, before
        )
        processing = await asyncio.to_thread(
            repo.count_processing_queued_runs, campaign_id
        )
        return queued > 0 or processing > 0

    async def _monitor_completion(self) -> None:
        while self._running:
            try:
                await self._check_stale_campaigns()
            except Exception as exc:
                logger.error("Completion monitoring failed: %s", exc)
            await asyncio.sleep(self.completion_check_interval)

    async def _check_stale_campaigns(self) -> None:
        campaigns = await asyncio.to_thread(
            repo.get_campaigns_by_status, ["running"]
        )
        for campaign in campaigns:
            campaign_id = str(campaign["campaign_id"])
            try:
                if campaign_id in self._batch_in_progress:
                    started = self._batch_in_progress[campaign_id]
                    if (datetime.now(timezone.utc) - started).total_seconds() > 300:
                        del self._batch_in_progress[campaign_id]
                        if await self._has_pending_work(campaign_id):
                            await self._schedule_next_batch(campaign_id)
                            continue
                if campaign_id not in self._batch_in_progress:
                    if await self._has_pending_work(campaign_id):
                        if self._is_within_schedule(campaign):
                            await self._schedule_next_batch(campaign_id)
                        continue
                if await self._should_mark_complete(campaign):
                    await self._complete_campaign(campaign)
            except Exception as exc:
                logger.error("Completion check campaign=%s: %s", campaign_id, exc)

    async def _should_mark_complete(self, campaign: dict) -> bool:
        campaign_id = str(campaign["campaign_id"])
        if campaign_id in self._batch_in_progress:
            return False
        if await self._has_pending_work(campaign_id):
            return False
        last_activity = self._last_activity.get(campaign_id)
        if not last_activity:
            for key in ("last_activity_at", "last_batch_scheduled_at", "started_at"):
                raw = campaign.get(key)
                if raw:
                    try:
                        last_activity = datetime.fromisoformat(
                            str(raw).replace("Z", "+00:00")
                        )
                        break
                    except ValueError:
                        continue
        if last_activity:
            delta = datetime.now(timezone.utc) - last_activity
            if delta.total_seconds() < self.completion_timeout:
                return False
        return True

    async def _complete_campaign(self, campaign: dict) -> None:
        campaign_id = str(campaign["campaign_id"])
        if await self._has_pending_work(campaign_id):
            return
        await asyncio.to_thread(
            repo.update_campaign,
            campaign_id,
            state="completed",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        duration = None
        started = campaign.get("started_at")
        if started:
            try:
                start_dt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                duration = (datetime.now(timezone.utc) - start_dt).total_seconds()
            except ValueError:
                pass
        await self.publisher.publish_campaign_completed(
            campaign_id=campaign_id,
            total_rows=int(campaign.get("total_rows") or 0),
            processed_rows=int(campaign.get("processed_rows") or 0),
            failed_rows=int(campaign.get("failed_rows") or 0),
            duration_seconds=duration,
        )
        self._clear_campaign_state(campaign_id)

    async def shutdown(self) -> None:
        self._running = False
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe(CAMPAIGN_EVENTS_CHANNEL)
                await self._pubsub.aclose()
            except Exception:
                pass


async def main() -> None:
    redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    orchestrator = CampaignOrchestrator(redis)
    shutdown_event = asyncio.Event()
    loop = asyncio.get_event_loop()

    def signal_handler(_signum: int) -> None:
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler, sig)

    orchestrator_task = asyncio.create_task(orchestrator.run())
    shutdown_task = asyncio.create_task(shutdown_event.wait())
    done, _ = await asyncio.wait(
        [orchestrator_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
    )
    if shutdown_task in done:
        orchestrator._running = False
        orchestrator_task.cancel()
        try:
            await orchestrator_task
        except asyncio.CancelledError:
            pass
    await orchestrator.shutdown()
    await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
