"""Campaign-scoped call analytics aggregated from CallLogs."""

from __future__ import annotations

from typing import Any, get_args

from app.database import get_database
from app.models.schemas import CONNECTED_CALL_RESPONSE, CallResponse
from app.services.call_log_service import (
    COLLECTION,
    CallLogListFilters,
    build_call_log_query,
    connection_rate,
)
from app.services.campaign import campaign_repository as repo
from app.services.campaign.campaign_repository import CampaignNotFoundError

_CALL_RESPONSE_KEYS = get_args(CallResponse)


def get_campaign_analytics(org_id: str, campaign_id: str) -> dict[str, Any]:
    """Aggregate CallLogs for one campaign plus progress fields from the campaign doc.

    Disposition is ``call_response`` (see ``CallResponse``). Connected calls use
    ``CONNECTED_CALL_RESPONSE``.
    """
    campaign = repo.get_campaign_for_org(org_id, campaign_id)
    if not campaign:
        raise CampaignNotFoundError(campaign_id)

    match = build_call_log_query(
        org_id,
        CallLogListFilters(campaign_id=campaign_id),
    )
    connected_match = {"call_response": CONNECTED_CALL_RESPONSE}

    pipeline = [
        {"$match": match},
        {
            "$facet": {
                "attempted": [{"$count": "count"}],
                "connected": [
                    {"$match": connected_match},
                    {
                        "$group": {
                            "_id": None,
                            "count": {"$sum": 1},
                            "total_duration": {
                                "$sum": {"$ifNull": ["$duration", 0]}
                            },
                            "average_duration": {"$avg": "$duration"},
                        }
                    },
                ],
                "by_call_response": [
                    {
                        "$group": {
                            "_id": {"$ifNull": ["$call_response", "unknown"]},
                            "count": {"$sum": 1},
                        }
                    },
                    {"$sort": {"count": -1}},
                ],
            }
        },
    ]
    result = next(iter(get_database()[COLLECTION].aggregate(pipeline)), {})

    attempted = int(next(iter(result.get("attempted") or []), {}).get("count") or 0)
    connected_row = next(iter(result.get("connected") or []), {})
    connected = int(connected_row.get("count") or 0)
    total_duration = float(connected_row.get("total_duration") or 0.0)
    average_duration = float(connected_row.get("average_duration") or 0.0)

    by_call_response: dict[str, int] = {}
    for row in result.get("by_call_response") or []:
        key = str(row.get("_id") or "unknown")
        by_call_response[key] = int(row.get("count") or 0)

    def disposition_count(key: str) -> int:
        return int(by_call_response.get(key) or 0)

    # Named counters for known dispositions (API schema fields).
    disposition_fields = {
        f"calls_{key}": disposition_count(key)
        for key in _CALL_RESPONSE_KEYS
        if key != "pending" and key != CONNECTED_CALL_RESPONSE
    }
    # Schema uses calls_connected (not calls_answered) for the connected disposition.
    disposition_fields["calls_connected"] = connected

    total_rows = int(campaign.get("total_rows") or 0)
    processed_rows = int(campaign.get("processed_rows") or 0)
    failed_rows = int(campaign.get("failed_rows") or 0)

    return {
        "campaign_id": campaign_id,
        "state": campaign.get("state", "created"),
        "total_rows": total_rows,
        "processed_rows": processed_rows,
        "failed_rows": failed_rows,
        "progress_percentage": (processed_rows / total_rows * 100) if total_rows > 0 else 0.0,
        "calls_attempted": attempted,
        **disposition_fields,
        "connection_rate": connection_rate(attempted, connected),
        "total_duration_seconds": total_duration,
        "average_duration_seconds": average_duration,
        "by_call_response": by_call_response,
    }
