"""Background campaign tasks for ARQ workers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.services.campaign import campaign_repository as repo
from app.services.campaign.campaign_call_dispatcher import campaign_call_dispatcher
from app.services.campaign.campaign_event_publisher import get_campaign_event_publisher
from app.services.campaign.errors import (
    ConcurrentSlotAcquisitionError,
    PhoneNumberPoolExhaustedError,
)
from app.services.campaign.source_sync_factory import get_sync_service

logger = logging.getLogger(__name__)

PHONE_POOL_EXHAUSTED_KEY = "phone_number_pool_exhausted_attempts"
MAX_PHONE_POOL_ATTEMPTS = 3


async def sync_campaign_source(ctx: dict[str, Any], campaign_id: str) -> None:
    logger.info("Starting source sync for campaign %s", campaign_id)
    try:
        campaign = repo.get_campaign_by_id(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        sync_service = get_sync_service(str(campaign.get("source_type") or "csv"))
        rows_synced = await sync_service.sync_source_data(campaign_id)
        if rows_synced == 0:
            repo.update_campaign(
                campaign_id,
                state="completed",
                completed_at=datetime.now(timezone.utc).isoformat(),
                source_sync_status="completed",
                source_last_synced_at=datetime.now(timezone.utc).isoformat(),
            )
            return
        repo.update_campaign(
            campaign_id,
            state="running",
            source_sync_status="completed",
            source_last_synced_at=datetime.now(timezone.utc).isoformat(),
        )
        publisher = await get_campaign_event_publisher()
        await publisher.publish_sync_completed(
            campaign_id=campaign_id,
            total_rows=rows_synced,
            source_type=str(campaign.get("source_type") or ""),
            source_id=str(campaign.get("source_id") or ""),
        )
    except Exception as exc:
        logger.error("Error syncing campaign %s: %s", campaign_id, exc)
        repo.update_campaign(
            campaign_id,
            state="failed",
            source_sync_status="failed",
            source_sync_error=str(exc),
        )
        repo.append_campaign_log(
            campaign_id,
            level="error",
            event="source_sync_failed",
            message=f"Source sync failed: {exc}",
            details={"error": str(exc)},
        )
        raise


async def process_campaign_batch(
    ctx: dict[str, Any], campaign_id: str, batch_size: int | None = None
) -> None:
    size = batch_size or settings.CAMPAIGN_BATCH_SIZE
    logger.info("Processing batch campaign=%s size=%s", campaign_id, size)
    failed_count = 0
    try:
        processed_count = await campaign_call_dispatcher.process_batch(
            campaign_id, batch_size=size
        )
        if processed_count > 0:
            repo.reset_campaign_metadata_counter(
                campaign_id, key=PHONE_POOL_EXHAUSTED_KEY
            )
        publisher = await get_campaign_event_publisher()
        await publisher.publish_batch_completed(
            campaign_id=campaign_id,
            processed_count=processed_count,
            failed_count=failed_count,
            batch_size=size,
        )
    except ConcurrentSlotAcquisitionError as exc:
        publisher = await get_campaign_event_publisher()
        await publisher.publish_batch_failed(
            campaign_id=campaign_id,
            error=str(exc),
            processed_count=0,
        )
        repo.update_campaign(campaign_id, state="failed")
        raise
    except PhoneNumberPoolExhaustedError as exc:
        attempt = repo.increment_campaign_metadata_counter(
            campaign_id, key=PHONE_POOL_EXHAUSTED_KEY
        )
        publisher = await get_campaign_event_publisher()
        if attempt < MAX_PHONE_POOL_ATTEMPTS:
            await publisher.publish_batch_completed(
                campaign_id=campaign_id,
                processed_count=0,
                failed_count=0,
                batch_size=size,
            )
            return
        await publisher.publish_batch_failed(
            campaign_id=campaign_id,
            error=str(exc),
            processed_count=0,
        )
        repo.update_campaign(campaign_id, state="failed")
        raise
    except Exception as exc:
        logger.error("Batch failed campaign=%s: %s", campaign_id, exc)
        publisher = await get_campaign_event_publisher()
        await publisher.publish_batch_failed(
            campaign_id=campaign_id,
            error=str(exc),
            processed_count=0,
        )
        repo.update_campaign(campaign_id, state="failed")
        raise
