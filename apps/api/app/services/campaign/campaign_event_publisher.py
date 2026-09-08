"""Campaign event publisher for orchestrator communication."""

from __future__ import annotations

import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.constants.campaign import CAMPAIGN_EVENTS_CHANNEL
from app.services.campaign.campaign_event_protocol import (
    BatchCompletedEvent,
    BatchFailedEvent,
    CampaignCompletedEvent,
    CircuitBreakerTrippedEvent,
    RetryNeededEvent,
    SyncCompletedEvent,
)

logger = logging.getLogger(__name__)

_campaign_publisher: CampaignEventPublisher | None = None
_campaign_redis_client: aioredis.Redis | None = None


class CampaignEventPublisher:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self.redis = redis_client

    async def publish_batch_completed(
        self,
        campaign_id: str,
        processed_count: int,
        failed_count: int = 0,
        batch_size: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event = BatchCompletedEvent(
            campaign_id=campaign_id,
            processed_count=processed_count,
            failed_count=failed_count,
            batch_size=batch_size,
            metadata=metadata,
        )
        await self.redis.publish(CAMPAIGN_EVENTS_CHANNEL, event.to_json())

    async def publish_batch_failed(
        self,
        campaign_id: str,
        error: str,
        processed_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event = BatchFailedEvent(
            campaign_id=campaign_id,
            error=error,
            processed_count=processed_count,
            metadata=metadata,
        )
        await self.redis.publish(CAMPAIGN_EVENTS_CHANNEL, event.to_json())

    async def publish_sync_completed(
        self,
        campaign_id: str,
        total_rows: int,
        source_type: str = "",
        source_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event = SyncCompletedEvent(
            campaign_id=campaign_id,
            total_rows=total_rows,
            source_type=source_type,
            source_id=source_id,
            metadata=metadata,
        )
        await self.redis.publish(CAMPAIGN_EVENTS_CHANNEL, event.to_json())

    async def publish_retry_needed(
        self,
        *,
        call_id: str,
        reason: str,
        campaign_id: str | None = None,
        queued_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event = RetryNeededEvent(
            campaign_id=campaign_id or "",
            call_id=call_id,
            queued_run_id=queued_run_id or "",
            reason=reason,
            metadata=metadata or {},
        )
        await self.redis.publish(CAMPAIGN_EVENTS_CHANNEL, event.to_json())
        logger.info(
            "Published retry event call_id=%s reason=%s campaign=%s",
            call_id,
            reason,
            campaign_id,
        )

    async def publish_campaign_completed(
        self,
        campaign_id: str,
        total_rows: int,
        processed_rows: int,
        failed_rows: int,
        duration_seconds: float | None = None,
    ) -> None:
        event = CampaignCompletedEvent(
            campaign_id=campaign_id,
            total_rows=total_rows,
            processed_rows=processed_rows,
            failed_rows=failed_rows,
            duration_seconds=duration_seconds,
        )
        await self.redis.publish(CAMPAIGN_EVENTS_CHANNEL, event.to_json())

    async def publish_circuit_breaker_tripped(
        self,
        campaign_id: str,
        failure_rate: float,
        failure_count: int,
        success_count: int,
        threshold: float,
        window_seconds: int,
    ) -> None:
        event = CircuitBreakerTrippedEvent(
            campaign_id=campaign_id,
            failure_rate=failure_rate,
            failure_count=failure_count,
            success_count=success_count,
            threshold=threshold,
            window_seconds=window_seconds,
        )
        await self.redis.publish(CAMPAIGN_EVENTS_CHANNEL, event.to_json())
        logger.warning(
            "Circuit breaker tripped campaign=%s failure_rate=%.2f",
            campaign_id,
            failure_rate,
        )


async def get_campaign_event_publisher() -> CampaignEventPublisher:
    global _campaign_publisher, _campaign_redis_client
    if _campaign_publisher is None:
        _campaign_redis_client = await aioredis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
        _campaign_publisher = CampaignEventPublisher(_campaign_redis_client)
    return _campaign_publisher
