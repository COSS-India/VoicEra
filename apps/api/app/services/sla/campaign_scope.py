"""Load a campaign and its CallLogs / CallMetrics for SLA routes."""

from __future__ import annotations

from typing import Any

from app.database import get_database
from app.services.call_log_service import COLLECTION as CALL_LOGS
from app.services.call_metrics_service import COLLECTION as CALL_METRICS
from app.services.campaign import campaign_repository as repo
from app.services.campaign.campaign_repository import CampaignNotFoundError
from app.utils.mongo_utils import prepare_mongo_response

__all__ = [
    "CampaignNotFoundError",
    "load_campaign",
    "list_campaign_calls",
    "list_campaign_metrics",
    "campaign_call_ids",
]


def load_campaign(org_id: str, campaign_id: str) -> dict[str, Any]:
    doc = repo.get_campaign_for_org(org_id, campaign_id)
    prepared = prepare_mongo_response(doc) or {}
    prepared.pop("_id", None)
    return prepared


def list_campaign_calls(
    org_id: str,
    campaign_id: str,
    *,
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    cursor = (
        get_database()[CALL_LOGS]
        .find({"org_id": org_id, "campaign_id": campaign_id})
        .sort("created_at", -1)
        .limit(limit)
    )
    rows: list[dict[str, Any]] = []
    for doc in cursor:
        prepared = prepare_mongo_response(doc) or {}
        prepared.pop("_id", None)
        rows.append(prepared)
    return rows


def campaign_call_ids(calls: list[dict[str, Any]]) -> list[str]:
    return [str(c["call_id"]) for c in calls if c.get("call_id")]


def list_campaign_metrics(
    org_id: str,
    call_ids: list[str],
) -> list[dict[str, Any]]:
    if not call_ids:
        return []
    cursor = get_database()[CALL_METRICS].find(
        {"org_id": org_id, "call_id": {"$in": call_ids}}
    )
    rows: list[dict[str, Any]] = []
    for doc in cursor:
        prepared = prepare_mongo_response(doc) or {}
        prepared.pop("_id", None)
        rows.append(prepared)
    return rows
