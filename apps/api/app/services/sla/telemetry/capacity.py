"""Campaign capacity metrics from Redis slots and call overlap."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.call_concurrency.rate_limiter import rate_limiter
from app.services.sla import targets
from app.services.sla.campaign_scope import list_campaign_calls, load_campaign
from app.services.sla.metrics import metric, no_data_metric
from app.services.sla.status_rules import threshold_operating

logger = logging.getLogger(__name__)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def peak_overlap(calls: list[dict[str, Any]]) -> int | None:
    """Max concurrent calls from start/end timestamps. None if over scan cap."""
    if len(calls) > targets.MAX_CALLS_FOR_PEAK_OVERLAP:
        return None
    events: list[tuple[datetime, int]] = []
    now = datetime.now(timezone.utc)
    for call in calls:
        start = _parse_iso(call.get("start_time_utc") or call.get("created_at"))
        if start is None:
            continue
        end = _parse_iso(call.get("end_time_utc")) or now
        if end < start:
            end = start
        events.append((start, 1))
        events.append((end, -1))
    if not events:
        return 0
    events.sort(key=lambda item: (item[0], item[1]))
    live = 0
    peak = 0
    for _, delta in events:
        live += delta
        if live > peak:
            peak = live
    return peak


async def live_calls_for_campaign(campaign_id: str) -> int | None:
    """Count active slots for ``campaign:{id}``. None if Redis is unreachable."""
    key = f"concurrent_calls:campaign:{campaign_id}"
    try:
        redis = await rate_limiter._get_redis()
        now = datetime.now(timezone.utc).timestamp()
        stale_cutoff = now - rate_limiter.stale_call_timeout
        await redis.zremrangebyscore(key, 0, stale_cutoff)
        return int(await redis.zcard(key))
    except Exception as exc:
        logger.warning("Campaign live-call count failed: %s", exc)
        return None


async def collect_capacity(org_id: str, campaign_id: str) -> dict[str, Any]:
    campaign = load_campaign(org_id, campaign_id)
    calls = list_campaign_calls(
        org_id, campaign_id, limit=targets.MAX_CALLS_FOR_PEAK_OVERLAP + 1
    )
    live = await live_calls_for_campaign(campaign_id)
    peak = peak_overlap(calls) if len(calls) <= targets.MAX_CALLS_FOR_PEAK_OVERLAP else None

    metrics = [
        metric(
            key="calls_live_now",
            label="Calls live now",
            target=float(targets.COMMITTED_CAPACITY),
            comparator="lte",
            unit="calls",
            actual=float(live) if live is not None else None,
            source="redis" if live is not None else "redis_unavailable",
            scope="campaign",
        ),
        metric(
            key="peak_calls",
            label="Peak calls",
            target=float(targets.EXPECTED_PEAK_CALLS),
            comparator="lte",
            unit="calls",
            actual=float(peak) if peak is not None else None,
            source="call_logs" if peak is not None else "scan_limit_exceeded",
            scope="campaign",
        ),
        no_data_metric(
            key="calls_rejected_below_limit",
            label=f"Calls rejected below {targets.COMMITTED_CAPACITY}",
            target=targets.REJECTED_BELOW_LIMIT_PCT,
            comparator="lte",
            unit="pct",
            source="rejections_not_persisted",
            scope="campaign",
        ),
        metric(
            key="committed_capacity",
            label="Committed capacity",
            target=float(targets.COMMITTED_CAPACITY),
            comparator="gte",
            unit="calls",
            actual=float(targets.COMMITTED_CAPACITY),
            source="sla_target",
            scope="deployment",
            operating_status="working_normally",
        ),
    ]
    for row in metrics:
        if row["key"] == "calls_rejected_below_limit":
            row["operating_status"] = threshold_operating(
                row["actual"], target=row["target"], comparator=row["comparator"]
            )

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign.get("name"),
        "scope": "campaign",
        "call_count": len(calls),
        "metrics": metrics,
    }
