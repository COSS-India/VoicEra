"""MongoDB persistence for campaigns and queued runs."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument

from app.config import settings
from app.constants.campaign import (
    DEFAULT_CAMPAIGN_RETRY_CONFIG,
    DEFAULT_ORG_CONCURRENCY_LIMIT,
)
from app.database import get_database
from app.utils.mongo_utils import prepare_mongo_response, prepare_mongo_response_list

logger = logging.getLogger(__name__)

CAMPAIGNS = "Campaigns"
QUEUED_RUNS = "QueuedRuns"
ORGANIZATIONS = "Organizations"


class CampaignNotFoundError(Exception):
    def __init__(self, campaign_id: str) -> None:
        self.campaign_id = campaign_id
        super().__init__(f"Campaign not found: {campaign_id}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    prepared = prepare_mongo_response(doc) or {}
    prepared.pop("_id", None)
    return prepared


def get_org_concurrent_limit(org_id: str) -> int:
    org = get_database()[ORGANIZATIONS].find_one({"org_id": org_id})
    if org and org.get("concurrent_call_limit") is not None:
        try:
            return max(1, int(org["concurrent_call_limit"]))
        except (TypeError, ValueError):
            pass
    return DEFAULT_ORG_CONCURRENCY_LIMIT


def create_campaign(doc: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    campaign_id = str(uuid.uuid4())
    record = {
        "campaign_id": campaign_id,
        "org_id": doc["org_id"],
        "name": doc["name"],
        "agent_id": doc["agent_id"],
        "source_type": doc.get("source_type", "csv"),
        "source_id": doc["source_id"],
        "state": "created",
        "total_rows": 0,
        "processed_rows": 0,
        "failed_rows": 0,
        "rate_limit_per_second": doc.get("rate_limit_per_second", 1),
        "retry_config": doc.get("retry_config") or dict(DEFAULT_CAMPAIGN_RETRY_CONFIG),
        "orchestrator_metadata": doc.get("orchestrator_metadata") or {},
        "from_number": doc.get("from_number"),
        "logs": [],
        "created_by": doc.get("created_by"),
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "source_sync_status": None,
        "source_sync_error": None,
        "source_last_synced_at": None,
        "last_batch_scheduled_at": None,
        "last_activity_at": None,
    }
    get_database()[CAMPAIGNS].insert_one(record)
    return _to_doc(record) or {}


def get_campaign_by_id(campaign_id: str) -> dict[str, Any] | None:
    return _to_doc(get_database()[CAMPAIGNS].find_one({"campaign_id": campaign_id}))


def get_campaign_for_org(org_id: str, campaign_id: str) -> dict[str, Any]:
    doc = get_database()[CAMPAIGNS].find_one(
        {"campaign_id": campaign_id, "org_id": org_id}
    )
    if not doc:
        raise CampaignNotFoundError(campaign_id)
    return _to_doc(doc) or {}


def list_campaigns(org_id: str) -> list[dict[str, Any]]:
    cursor = (
        get_database()[CAMPAIGNS]
        .find({"org_id": org_id})
        .sort("created_at", -1)
    )
    return prepare_mongo_response_list(
        [{k: v for k, v in d.items() if k != "_id"} for d in cursor]
    )


def update_campaign(campaign_id: str, **fields: Any) -> dict[str, Any] | None:
    patch = {k: v for k, v in fields.items() if v is not None or k in {
        "source_sync_error", "completed_at", "started_at"
    }}
    patch["updated_at"] = _now_iso()
    result = get_database()[CAMPAIGNS].update_one(
        {"campaign_id": campaign_id},
        {"$set": patch},
    )
    if result.matched_count == 0:
        return None
    return get_campaign_by_id(campaign_id)


def append_campaign_log(
    campaign_id: str,
    *,
    level: str,
    event: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    entry = {
        "timestamp": _now_iso(),
        "level": level,
        "event": event,
        "message": message,
        "details": details or {},
    }
    get_database()[CAMPAIGNS].update_one(
        {"campaign_id": campaign_id},
        {"$push": {"logs": entry}, "$set": {"updated_at": _now_iso()}},
    )


def increment_campaign_metadata_counter(
    campaign_id: str, key: str, amount: int = 1
) -> int:
    campaign = get_campaign_by_id(campaign_id)
    if not campaign:
        return 0
    metadata = dict(campaign.get("orchestrator_metadata") or {})
    counters = dict(metadata.get("counters") or {})
    counters[key] = int(counters.get(key, 0)) + amount
    metadata["counters"] = counters
    update_campaign(campaign_id, orchestrator_metadata=metadata)
    return int(counters[key])


def reset_campaign_metadata_counter(campaign_id: str, key: str) -> None:
    campaign = get_campaign_by_id(campaign_id)
    if not campaign:
        return
    metadata = dict(campaign.get("orchestrator_metadata") or {})
    counters = dict(metadata.get("counters") or {})
    counters.pop(key, None)
    metadata["counters"] = counters
    update_campaign(campaign_id, orchestrator_metadata=metadata)


def bulk_create_queued_runs(runs: list[dict[str, Any]]) -> int:
    if not runs:
        return 0
    now = _now_iso()
    docs = []
    for run in runs:
        docs.append(
            {
                "queued_run_id": str(uuid.uuid4()),
                "campaign_id": run["campaign_id"],
                "source_uuid": run["source_uuid"],
                "context_variables": run.get("context_variables") or {},
                "state": run.get("state", "queued"),
                "retry_count": run.get("retry_count", 0),
                "parent_queued_run_id": run.get("parent_queued_run_id"),
                "scheduled_for": run.get("scheduled_for"),
                "retry_reason": run.get("retry_reason"),
                "call_id": None,
                "created_at": now,
                "claimed_at": None,
                "processed_at": None,
            }
        )
    get_database()[QUEUED_RUNS].insert_many(docs)
    return len(docs)


def create_queued_run(**fields: Any) -> dict[str, Any]:
    now = _now_iso()
    doc = {
        "queued_run_id": str(uuid.uuid4()),
        "campaign_id": fields["campaign_id"],
        "source_uuid": fields["source_uuid"],
        "context_variables": fields.get("context_variables") or {},
        "state": fields.get("state", "queued"),
        "retry_count": fields.get("retry_count", 0),
        "parent_queued_run_id": fields.get("parent_queued_run_id"),
        "scheduled_for": fields.get("scheduled_for"),
        "retry_reason": fields.get("retry_reason"),
        "call_id": None,
        "created_at": now,
        "claimed_at": None,
        "processed_at": None,
    }
    get_database()[QUEUED_RUNS].insert_one(doc)
    return _to_doc(doc) or {}


def get_queued_run_by_id(queued_run_id: str) -> dict[str, Any] | None:
    return _to_doc(
        get_database()[QUEUED_RUNS].find_one({"queued_run_id": queued_run_id})
    )


def claim_queued_runs_for_processing(
    campaign_id: str,
    *,
    scheduled_before: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    before_iso = scheduled_before.isoformat()
    claimed: list[dict[str, Any]] = []
    collection = get_database()[QUEUED_RUNS]
    for _ in range(limit):
        doc = collection.find_one_and_update(
            {
                "campaign_id": campaign_id,
                "state": "queued",
                "$or": [
                    {"scheduled_for": None},
                    {"scheduled_for": {"$lte": before_iso}},
                ],
            },
            {"$set": {"state": "processing", "claimed_at": _now_iso()}},
            sort=[("scheduled_for", 1), ("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            break
        claimed.append(_to_doc(doc) or {})
    return claimed


def return_processing_queued_runs_without_call(
    queued_run_ids: list[str],
) -> int:
    if not queued_run_ids:
        return 0
    result = get_database()[QUEUED_RUNS].update_many(
        {
            "queued_run_id": {"$in": queued_run_ids},
            "state": "processing",
            "call_id": None,
        },
        {"$set": {"state": "queued", "claimed_at": None}},
    )
    return int(result.modified_count)


def update_queued_run(queued_run_id: str, **fields: Any) -> dict[str, Any] | None:
    patch = {k: v for k, v in fields.items()}
    get_database()[QUEUED_RUNS].update_one(
        {"queued_run_id": queued_run_id},
        {"$set": patch},
    )
    return get_queued_run_by_id(queued_run_id)


def count_pending_queued_runs(campaign_id: str, before_iso: str) -> int:
    return get_database()[QUEUED_RUNS].count_documents(
        {
            "campaign_id": campaign_id,
            "state": "queued",
            "$or": [
                {"scheduled_for": None},
                {"scheduled_for": {"$lte": before_iso}},
            ],
        }
    )


def count_processing_queued_runs(campaign_id: str) -> int:
    return get_database()[QUEUED_RUNS].count_documents(
        {"campaign_id": campaign_id, "state": "processing"}
    )


def get_campaigns_by_status(statuses: list[str]) -> list[dict[str, Any]]:
    cursor = get_database()[CAMPAIGNS].find({"state": {"$in": statuses}})
    return prepare_mongo_response_list(
        [{k: v for k, v in d.items() if k != "_id"} for d in cursor]
    )


def delete_campaign(campaign_id: str) -> bool:
    result = get_database()[CAMPAIGNS].delete_one({"campaign_id": campaign_id})
    return result.deleted_count > 0


def delete_queued_runs_for_campaign(campaign_id: str) -> int:
    result = get_database()[QUEUED_RUNS].delete_many({"campaign_id": campaign_id})
    return result.deleted_count


def get_redial_candidates(campaign_id: str) -> list[dict[str, Any]]:
    """Queued runs whose linked calls ended without answer."""
    from app.services.call_log_service import list_call_logs_by_campaign

    campaign = get_campaign_by_id(campaign_id)
    if not campaign:
        return []
    org_id = str(campaign.get("org_id") or "")
    calls = list_call_logs_by_campaign(org_id, campaign_id, limit=10000, offset=0)
    failed_responses = {"busy", "no_answer", "failed", "cancelled", "voicemail"}
    failed_call_ids = {
        c["call_id"]
        for c in calls
        if str(c.get("call_response") or "") in failed_responses
    }
    if not failed_call_ids:
        return []
    cursor = get_database()[QUEUED_RUNS].find(
        {"campaign_id": campaign_id, "call_id": {"$in": list(failed_call_ids)}}
    )
    return prepare_mongo_response_list(
        [{k: v for k, v in d.items() if k != "_id"} for d in cursor]
    )
