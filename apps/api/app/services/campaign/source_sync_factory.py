"""Factory for campaign source sync services."""

from __future__ import annotations

from app.services.campaign.source_sync import CampaignSourceSyncService
from app.services.campaign.sources.csv import CSVSyncService


def get_sync_service(source_type: str) -> CampaignSourceSyncService:
    if source_type == "csv":
        return CSVSyncService()
    raise ValueError(f"Unsupported campaign source type: {source_type}")
