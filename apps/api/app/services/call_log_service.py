"""CallLogs collection CRUD for outbound and inbound call records."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import get_database
from app.utils.mongo_utils import prepare_mongo_response

logger = logging.getLogger(__name__)

COLLECTION = "CallLogs"
CAMPAIGNS_COLLECTION = "Campaigns"


@dataclass(frozen=True)
class CallLogListFilters:
    """Server-side filters for CallLogs list/count queries."""

    campaign_id: str | None = None
    exclude_campaign: bool = False
    agent_id: str | None = None
    status: str | None = None
    call_type: str | None = None
    call_response: str | None = None
    created_after: str | None = None
    created_before: str | None = None


class CallLogNotFoundError(Exception):
    """Raised when a call log is missing for the organisation."""

    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        super().__init__(f"Call log not found: {call_id}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_response(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    prepared = prepare_mongo_response(doc) or {}
    prepared.pop("_id", None)
    return prepared


def _has_end_time(doc: dict[str, Any]) -> bool:
    end_time = doc.get("end_time_utc")
    return bool(end_time and str(end_time).strip())


def _compute_duration_seconds(start_time_utc: str | None, end_time_utc: str) -> float | None:
    if not start_time_utc:
        return None
    try:
        start = datetime.fromisoformat(str(start_time_utc).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(end_time_utc).replace("Z", "+00:00"))
        return max(0.0, (end - start).total_seconds())
    except ValueError:
        return None


def create_call_log(doc: dict[str, Any]) -> dict[str, Any]:
    """Insert a new CallLogs document."""
    get_database()[COLLECTION].insert_one(doc)
    logger.info(
        "CallLog created call_id=%s org=%s status=%s",
        doc.get("call_id"),
        doc.get("org_id"),
        doc.get("status"),
    )
    return _to_response(doc) or {}


def update_call_log(call_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Update fields on an existing call log by ``call_id``."""
    patch = dict(patch)
    patch["updated_at"] = _now_iso()
    result = get_database()[COLLECTION].update_one(
        {"call_id": call_id},
        {"$set": patch},
    )
    if result.matched_count == 0:
        raise CallLogNotFoundError(call_id)
    doc = get_database()[COLLECTION].find_one({"call_id": call_id})
    logger.info(
        "CallLog updated call_id=%s fields=%s",
        call_id,
        list(patch.keys()),
    )
    return _to_response(doc) or {}


def patch_call_log(org_id: str, call_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Update fields on a call log scoped to ``org_id``."""
    patch = dict(patch)
    doc = get_database()[COLLECTION].find_one({"org_id": org_id, "call_id": call_id})
    if not doc:
        raise CallLogNotFoundError(call_id)

    # Answered is sticky: later telephony updates must not overwrite disposition/status.
    if doc.get("call_response") == "answered":
        patch.pop("call_response", None)
        patch.pop("status", None)

    end_time_utc = patch.get("end_time_utc")
    if end_time_utc is not None:
        if _has_end_time(doc):
            logger.debug("CallLog end_time already set call_id=%s", call_id)
            patch.pop("end_time_utc", None)
            patch.pop("duration", None)
        elif patch.get("duration") is None:
            computed = _compute_duration_seconds(doc.get("start_time_utc"), str(end_time_utc))
            if computed is not None:
                patch["duration"] = computed

    if not patch:
        return _to_response(doc) or {}

    patch["updated_at"] = _now_iso()
    result = get_database()[COLLECTION].update_one(
        {"org_id": org_id, "call_id": call_id},
        {"$set": patch},
    )
    if result.matched_count == 0:
        raise CallLogNotFoundError(call_id)
    doc = get_database()[COLLECTION].find_one({"org_id": org_id, "call_id": call_id})
    logger.info(
        "CallLog patched call_id=%s org=%s fields=%s",
        call_id,
        org_id,
        list(patch.keys()),
    )
    return _to_response(doc) or {}


def patch_call_log_by_provider_sid(
    org_id: str,
    provider_call_sid: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Patch a call log located by provider call SID."""
    doc = get_call_log_by_provider_sid(org_id, provider_call_sid)
    if not doc:
        raise CallLogNotFoundError(provider_call_sid)
    call_id = str(doc.get("call_id") or "")
    if not call_id:
        raise CallLogNotFoundError(provider_call_sid)
    return patch_call_log(org_id, call_id, patch)


def transform_call_log_urls(
    doc: dict[str, Any],
    *,
    api_prefix: str = "/api/v1",
) -> dict[str, Any]:
    """Rewrite ``minio://`` artifact URLs to authenticated API proxy paths."""
    result = dict(doc)
    call_id = str(result.get("call_id") or "")
    if not call_id:
        return result
    if str(result.get("recording_url") or "").startswith("minio://"):
        result["recording_url"] = f"{api_prefix}/calls/{call_id}/recording"
    if str(result.get("transcript_url") or "").startswith("minio://"):
        result["transcript_url"] = f"{api_prefix}/calls/{call_id}/transcript"
    return result


def get_call_log(org_id: str, call_id: str) -> dict[str, Any]:
    """Fetch one call log scoped to ``org_id``."""
    doc = get_database()[COLLECTION].find_one(
        {"org_id": org_id, "call_id": call_id}
    )
    if not doc:
        raise CallLogNotFoundError(call_id)
    result = _to_response(doc) or {}
    enriched = _enrich_with_campaign_names(org_id, [result])
    return enriched[0] if enriched else result


def get_call_log_by_provider_sid(
    org_id: str,
    provider_call_sid: str,
) -> dict[str, Any] | None:
    """Fetch a call log by provider SID, or ``None`` if not found."""
    if not provider_call_sid:
        return None
    doc = get_database()[COLLECTION].find_one(
        {"org_id": org_id, "provider_call_sid": provider_call_sid}
    )
    return _to_response(doc)


def build_call_log_query(
    org_id: str,
    filters: CallLogListFilters | None = None,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Mongo query for CallLogs list/count/analytics match stages."""
    query: dict[str, Any] = {"org_id": org_id}
    if extra:
        query.update(extra)

    f = filters or CallLogListFilters()
    if f.exclude_campaign:
        # One-off calls: missing or null campaign_id
        query["$or"] = [
            {"campaign_id": {"$exists": False}},
            {"campaign_id": None},
        ]
    elif f.campaign_id:
        query["campaign_id"] = f.campaign_id

    if f.agent_id:
        query["agent_id"] = f.agent_id
    if f.status:
        query["status"] = f.status
    if f.call_type:
        query["call_type"] = f.call_type
    if f.call_response:
        query["call_response"] = f.call_response

    created_at: dict[str, str] = {}
    if f.created_after:
        created_at["$gte"] = f.created_after
    if f.created_before:
        created_at["$lte"] = f.created_before
    if created_at:
        query["created_at"] = created_at

    return query


def _list_query(org_id: str, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_call_log_query(org_id, extra=extra)


def _paginated_call_log_cursor(
    query: dict[str, Any],
    *,
    limit: int,
    offset: int,
):
    return (
        get_database()[COLLECTION]
        .find(query)
        .sort("created_at", -1)
        .skip(max(0, offset))
        .limit(max(1, min(limit, 500)))
    )


def _campaign_names_by_id(org_id: str, campaign_ids: set[str]) -> dict[str, str]:
    """Batched Campaigns lookup: campaign_id → name."""
    ids = {cid for cid in campaign_ids if cid}
    if not ids:
        return {}
    cursor = get_database()[CAMPAIGNS_COLLECTION].find(
        {"org_id": org_id, "campaign_id": {"$in": list(ids)}},
        {"campaign_id": 1, "name": 1},
    )
    return {
        str(doc["campaign_id"]): str(doc.get("name") or "")
        for doc in cursor
        if doc.get("campaign_id")
    }


def _enrich_with_campaign_names(
    org_id: str,
    logs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    names = _campaign_names_by_id(
        org_id,
        {str(log.get("campaign_id") or "") for log in logs},
    )
    for log in logs:
        cid = str(log.get("campaign_id") or "")
        if cid and cid in names:
            log["campaign_name"] = names[cid]
        elif cid:
            log["campaign_name"] = None
    return logs


def _prepare_call_log_list(docs) -> list[dict[str, Any]]:
    from app.utils.mongo_utils import prepare_mongo_response_list

    return prepare_mongo_response_list(
        [{k: v for k, v in doc.items() if k != "_id"} for doc in docs]
    )


def count_call_logs(
    org_id: str,
    filters: CallLogListFilters | None = None,
) -> int:
    """Count call logs for an organisation with optional filters."""
    return get_database()[COLLECTION].count_documents(
        build_call_log_query(org_id, filters)
    )


def count_call_logs_by_org(org_id: str) -> int:
    """Count call logs for an organisation."""
    return count_call_logs(org_id)


def list_call_logs(
    org_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    filters: CallLogListFilters | None = None,
    enrich_campaign_names: bool = True,
) -> list[dict[str, Any]]:
    """List call logs for an organisation with optional filters."""
    cursor = _paginated_call_log_cursor(
        build_call_log_query(org_id, filters),
        limit=limit,
        offset=offset,
    )
    logs = _prepare_call_log_list(cursor)
    if enrich_campaign_names:
        return _enrich_with_campaign_names(org_id, logs)
    return logs


def list_call_logs_by_org(
    org_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    filters: CallLogListFilters | None = None,
) -> list[dict[str, Any]]:
    """List call logs for an organisation."""
    return list_call_logs(org_id, limit=limit, offset=offset, filters=filters)


def list_call_logs_by_campaign(
    org_id: str,
    campaign_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    filters: CallLogListFilters | None = None,
    enrich_campaign_names: bool = True,
) -> list[dict[str, Any]]:
    """List call logs for a campaign scoped to ``org_id``."""
    base = CallLogListFilters(campaign_id=campaign_id)
    if filters:
        merged = CallLogListFilters(
            campaign_id=campaign_id,
            exclude_campaign=False,
            agent_id=filters.agent_id,
            status=filters.status,
            call_type=filters.call_type,
            call_response=filters.call_response,
            created_after=filters.created_after,
            created_before=filters.created_before,
        )
    else:
        merged = base
    return list_call_logs(
        org_id,
        limit=limit,
        offset=offset,
        filters=merged,
        enrich_campaign_names=enrich_campaign_names,
    )


def _connection_rate(attempted: int, connected: int) -> float:
    if attempted <= 0:
        return 0.0
    return round((connected / attempted) * 100, 1)


def get_call_analytics(
    org_id: str,
    filters: CallLogListFilters | None = None,
) -> dict[str, Any]:
    """Aggregate CallLogs for an org, optionally scoped by ``filters`` (e.g. campaign).

    ``calls_connected`` / connection rate use ``call_response == "answered"``.
    """
    match = build_call_log_query(org_id, filters)
    connected_match = {"call_response": "answered"}

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
    by_call_response: dict[str, int] = {}
    for row in result.get("by_call_response") or []:
        key = str(row.get("_id") or "unknown")
        by_call_response[key] = int(row.get("count") or 0)

    return {
        "calls_attempted": attempted,
        "calls_connected": connected,
        "connection_rate": _connection_rate(attempted, connected),
        "total_duration_seconds": float(connected_row.get("total_duration") or 0.0),
        "average_duration_seconds": float(connected_row.get("average_duration") or 0.0),
        "by_call_response": by_call_response,
    }


def _model_usage_pipeline(stage: str) -> list[dict[str, Any]]:
    """Sub-pipeline (for use inside the analytics $facet) ranking models for
    one pipeline stage ("stt"/"tts"/"llm") by how many calls actually used
    them — via each call's agent_id joined against that agent's current
    model config — rather than by how many agents happen to be configured
    with it.

    ``config.models`` is language-keyed; we resolve the primary language stack.
    """
    stage_field = f"_primary_stack.{stage}_config"
    return [
        {"$match": {"agent_id": {"$ne": None}}},
        {"$group": {"_id": "$agent_id", "call_count": {"$sum": 1}}},
        {
            "$lookup": {
                "from": "Agents",
                "localField": "_id",
                "foreignField": "agent_id",
                "as": "agent",
            }
        },
        {"$unwind": "$agent"},
        {
            "$addFields": {
                "_primary_stack": {
                    "$getField": {
                        "field": "$agent.config.language.primary",
                        "input": "$agent.config.models",
                    }
                }
            }
        },
        {
            "$group": {
                "_id": {
                    "model": f"${stage_field}.model",
                    "provider": f"${stage_field}.provider",
                },
                "call_count": {"$sum": "$call_count"},
            }
        },
        {"$match": {"_id.model": {"$ne": None}}},
        {"$sort": {"call_count": -1}},
        {"$limit": 1},
    ]


def get_org_call_analytics(org_id: str) -> dict[str, Any]:
    """All-time call analytics for an organisation, plus a trailing-week trend.

    ``created_at`` is stored as an ISO-8601 UTC string (see ``_now_iso``), so
    lexicographic comparison against ISO cutoff strings sorts the same as
    chronological comparison — no ``$toDate`` conversion needed, matching the
    string-sort convention already used for ``created_at`` elsewhere in this
    module.
    """
    now = datetime.now(timezone.utc)
    this_week_start = (now - timedelta(days=7)).isoformat()
    last_week_start = (now - timedelta(days=14)).isoformat()

    connected_match = {"call_response": "answered"}

    pipeline = [
        {"$match": _list_query(org_id)},
        {
            "$facet": {
                "attempted": [{"$count": "count"}],
                "connected": [
                    {"$match": connected_match},
                    {
                        "$group": {
                            "_id": None,
                            "count": {"$sum": 1},
                            "total_duration": {"$sum": {"$ifNull": ["$duration", 0]}},
                            "average_duration": {"$avg": "$duration"},
                        }
                    },
                ],
                "by_agent": [
                    {
                        "$group": {
                            "_id": {"agent_id": "$agent_id", "agent_name": "$agent_name"},
                            "count": {"$sum": 1},
                        }
                    },
                    {"$sort": {"count": -1}},
                    {"$limit": 10},
                ],
                "this_week": [
                    {"$match": {"created_at": {"$gte": this_week_start}}},
                    {
                        "$group": {
                            "_id": None,
                            "attempted": {"$sum": 1},
                            "connected": {
                                "$sum": {
                                    "$cond": [
                                        {"$eq": ["$call_response", "answered"]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                ],
                "last_week": [
                    {
                        "$match": {
                            "created_at": {"$gte": last_week_start, "$lt": this_week_start}
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "attempted": {"$sum": 1},
                            "connected": {
                                "$sum": {
                                    "$cond": [
                                        {"$eq": ["$call_response", "answered"]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                ],
                **{
                    f"model_usage_{stage}": _model_usage_pipeline(stage)
                    for stage in ("stt", "tts", "llm")
                },
            }
        },
    ]
    result = next(iter(get_database()[COLLECTION].aggregate(pipeline)), {})

    attempted = int(next(iter(result.get("attempted") or []), {}).get("count") or 0)
    connected_row = next(iter(result.get("connected") or []), {})
    connected = int(connected_row.get("count") or 0)
    total_duration = float(connected_row.get("total_duration") or 0.0)
    average_duration = float(connected_row.get("average_duration") or 0.0)

    this_week = next(iter(result.get("this_week") or []), {})
    last_week = next(iter(result.get("last_week") or []), {})
    this_week_rate = _connection_rate(
        int(this_week.get("attempted") or 0), int(this_week.get("connected") or 0)
    )
    last_week_attempted = int(last_week.get("attempted") or 0)
    last_week_rate = _connection_rate(last_week_attempted, int(last_week.get("connected") or 0))
    trend_vs_last_week_pct = (
        round(this_week_rate - last_week_rate, 1) if last_week_attempted > 0 else None
    )

    agent_performance = [
        {
            "agent_id": (row.get("_id") or {}).get("agent_id"),
            "agent_name": (row.get("_id") or {}).get("agent_name"),
            "call_count": int(row.get("count") or 0),
        }
        for row in (result.get("by_agent") or [])
    ]

    model_usage = {}
    for stage in ("stt", "tts", "llm"):
        row = next(iter(result.get(f"model_usage_{stage}") or []), None)
        if row:
            model_usage[stage] = {
                "model": (row.get("_id") or {}).get("model"),
                "provider": (row.get("_id") or {}).get("provider"),
                "call_count": int(row.get("call_count") or 0),
            }

    return {
        "calls_attempted": attempted,
        "calls_connected": connected,
        "calls_failed": max(0, attempted - connected),
        "connection_rate": _connection_rate(attempted, connected),
        "total_duration_seconds": total_duration,
        "average_duration_seconds": average_duration,
        "trend_vs_last_week_pct": trend_vs_last_week_pct,
        "agent_performance": agent_performance,
        "model_usage": model_usage,
    }
