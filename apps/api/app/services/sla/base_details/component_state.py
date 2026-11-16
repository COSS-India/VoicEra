"""Persist when each SLA component last became working or not working."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import get_database

COLLECTION = "SlaComponentState"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_component_state(
    *,
    component_id: str,
    scope: str,
    status: str,
    org_id: str | None = None,
    campaign_id: str | None = None,
) -> dict[str, Any]:
    """Keep ``since`` when status is unchanged; reset ``since`` on a flip."""
    # Empty strings instead of null so a unique index stays one row per key.
    query: dict[str, Any] = {
        "component_id": component_id,
        "scope": scope,
        "org_id": org_id or "",
        "campaign_id": campaign_id or "",
    }
    coll = get_database()[COLLECTION]
    existing = coll.find_one(query)
    now = _now_iso()
    if existing and existing.get("status") == status:
        since = existing.get("since") or now
        coll.update_one(
            {"_id": existing["_id"]},
            {"$set": {"updated_at": now}},
        )
        return {
            "component_id": component_id,
            "status": status,
            "since": since,
            "updated_at": now,
        }

    doc = {
        **query,
        "status": status,
        "since": now,
        "updated_at": now,
    }
    if existing:
        coll.update_one({"_id": existing["_id"]}, {"$set": doc})
    else:
        coll.insert_one(doc)
    return {
        "component_id": component_id,
        "status": status,
        "since": now,
        "updated_at": now,
    }


def duration_seconds(since: str | None, now: datetime | None = None) -> int | None:
    if not since:
        return None
    try:
        stamp = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return max(0, int((current - stamp).total_seconds()))
