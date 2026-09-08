"""Campaign lifecycle: start, pause, resume."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.campaign import campaign_repository as repo
from app.services.campaign.campaign_event_publisher import get_campaign_event_publisher
from app.services.campaign.circuit_breaker import circuit_breaker
from app.tasks.arq import enqueue_job
from app.tasks.function_names import FunctionNames

logger = logging.getLogger(__name__)


class CampaignRunnerService:
    async def start_campaign(self, campaign_id: str) -> None:
        campaign = repo.get_campaign_by_id(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        if campaign.get("state") != "created":
            raise ValueError(
                f"Campaign must be in 'created' state, current: {campaign.get('state')}"
            )

        metadata = campaign.get("orchestrator_metadata") or {}
        is_redial = bool(metadata.get("parent_campaign_id"))
        if is_redial:
            now = datetime.now(timezone.utc).isoformat()
            repo.update_campaign(
                campaign_id,
                state="running",
                started_at=now,
                source_last_synced_at=now,
            )
            publisher = await get_campaign_event_publisher()
            await publisher.publish_sync_completed(
                campaign_id=campaign_id,
                total_rows=int(campaign.get("total_rows") or 0),
                source_type=str(campaign.get("source_type") or ""),
                source_id=str(campaign.get("source_id") or ""),
            )
            return

        repo.update_campaign(
            campaign_id,
            state="syncing",
            started_at=datetime.now(timezone.utc).isoformat(),
            source_sync_status="in_progress",
        )
        await enqueue_job(FunctionNames.SYNC_CAMPAIGN_SOURCE, campaign_id)

    async def pause_campaign(self, campaign_id: str) -> None:
        campaign = repo.get_campaign_by_id(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        if campaign.get("state") not in ("running", "syncing"):
            raise ValueError(
                f"Campaign must be running or syncing, current: {campaign.get('state')}"
            )
        repo.update_campaign(campaign_id, state="paused")

    async def resume_campaign(self, campaign_id: str) -> None:
        campaign = repo.get_campaign_by_id(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        if campaign.get("state") != "paused":
            raise ValueError(
                f"Campaign must be paused, current: {campaign.get('state')}"
            )
        repo.update_campaign(campaign_id, state="running")
        await circuit_breaker.reset(campaign_id)

    async def get_campaign_status(self, campaign_id: str) -> dict[str, Any]:
        campaign = repo.get_campaign_by_id(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        total = int(campaign.get("total_rows") or 0)
        processed = int(campaign.get("processed_rows") or 0)
        return {
            "campaign_id": campaign_id,
            "state": campaign.get("state"),
            "total_rows": total,
            "processed_rows": processed,
            "failed_rows": int(campaign.get("failed_rows") or 0),
            "progress_percentage": (processed / total * 100) if total > 0 else 0,
            "rate_limit": campaign.get("rate_limit_per_second"),
            "started_at": campaign.get("started_at"),
            "completed_at": campaign.get("completed_at"),
        }


campaign_runner_service = CampaignRunnerService()
