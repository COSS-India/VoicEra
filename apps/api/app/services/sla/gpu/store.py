"""Persist nvidia-smi samples and GPU restart readiness events."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.database import get_database
from app.services.sla import targets

logger = logging.getLogger(__name__)

SAMPLES = "GpuTelemetrySamples"
RESTARTS = "GpuRestartEvents"

# Keep roughly a month of 5-second samples is huge; retain 7 days.
SAMPLE_RETENTION = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def record_sample(
    *,
    healthy: bool,
    max_utilization_pct: float | None,
    gpu_count: int,
    reason: str | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _now()
    doc = {
        "sample_id": str(uuid4()),
        "recorded_at": now.isoformat(),
        "recorded_at_dt": now,
        "healthy": healthy,
        "max_utilization_pct": max_utilization_pct,
        "gpu_count": gpu_count,
        "above_peak_threshold": bool(
            max_utilization_pct is not None
            and max_utilization_pct >= targets.GPU_BUSY_ALERT_PCT
        ),
        "reason": reason,
        "raw": raw or {},
    }
    coll = get_database()[SAMPLES]
    coll.insert_one(doc)
    coll.delete_many({"recorded_at_dt": {"$lt": now - SAMPLE_RETENTION}})
    return {
        "sample_id": doc["sample_id"],
        "recorded_at": doc["recorded_at"],
        "healthy": healthy,
        "max_utilization_pct": max_utilization_pct,
    }


def list_samples_since(since: datetime) -> list[dict[str, Any]]:
    cursor = (
        get_database()[SAMPLES]
        .find({"recorded_at_dt": {"$gte": since}})
        .sort("recorded_at_dt", 1)
    )
    return list(cursor)


def begin_restart_event() -> str:
    """Record API/process start. Returns restart_id."""
    restart_id = str(uuid4())
    now = _now()
    get_database()[RESTARTS].insert_one(
        {
            "restart_id": restart_id,
            "started_at": now.isoformat(),
            "started_at_dt": now,
            "ready_at": None,
            "ready_secs": None,
            "status": "starting",
        }
    )
    return restart_id


def mark_restart_ready(restart_id: str) -> dict[str, Any] | None:
    coll = get_database()[RESTARTS]
    doc = coll.find_one({"restart_id": restart_id})
    if not doc:
        return None
    if doc.get("ready_at"):
        return doc
    now = _now()
    started = doc.get("started_at_dt")
    if not isinstance(started, datetime):
        try:
            started = datetime.fromisoformat(
                str(doc.get("started_at")).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            started = now
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    ready_secs = max(0.0, (now - started).total_seconds())
    coll.update_one(
        {"restart_id": restart_id},
        {
            "$set": {
                "ready_at": now.isoformat(),
                "ready_at_dt": now,
                "ready_secs": ready_secs,
                "status": "ready",
            }
        },
    )
    return coll.find_one({"restart_id": restart_id})


def latest_ready_restart() -> dict[str, Any] | None:
    return get_database()[RESTARTS].find_one(
        {"status": "ready", "ready_secs": {"$ne": None}},
        sort=[("ready_at_dt", -1)],
    )


def open_restart() -> dict[str, Any] | None:
    return get_database()[RESTARTS].find_one(
        {"status": "starting"},
        sort=[("started_at_dt", -1)],
    )


def aggregate_gpu_history(
    *,
    window: timedelta = timedelta(days=1),
    peak_threshold: float | None = None,
) -> dict[str, Any]:
    """Compute health-check success, healthy uptime, and time at/above peak."""
    if peak_threshold is None:
        peak_threshold = targets.GPU_BUSY_ALERT_PCT
    since = _now() - window
    samples = list_samples_since(since)
    total = len(samples)
    if total == 0:
        return {
            "sample_count": 0,
            "health_check_success_pct": None,
            "healthy_gpu_uptime_pct": None,
            "peak_utilization_pct": None,
            "peak_above_threshold_seconds": None,
            "window_seconds": int(window.total_seconds()),
        }

    healthy = sum(1 for s in samples if s.get("healthy"))
    utils = [
        float(s["max_utilization_pct"])
        for s in samples
        if s.get("max_utilization_pct") is not None
    ]
    peak = max(utils) if utils else None

    # Each sample represents ~5s when polled at that cadence; use gaps between
    # timestamps when available, else assume 5s per sample.
    above_seconds = 0.0
    for i, sample in enumerate(samples):
        util = sample.get("max_utilization_pct")
        if util is None or float(util) < peak_threshold:
            continue
        stamp = sample.get("recorded_at_dt")
        if i + 1 < len(samples) and isinstance(stamp, datetime):
            nxt = samples[i + 1].get("recorded_at_dt")
            if isinstance(nxt, datetime):
                above_seconds += max(0.0, (nxt - stamp).total_seconds())
                continue
        above_seconds += 5.0

    success_pct = round((healthy / total) * 100.0, 2)
    return {
        "sample_count": total,
        "health_check_success_pct": success_pct,
        "healthy_gpu_uptime_pct": success_pct,
        "peak_utilization_pct": peak,
        "peak_above_threshold_seconds": round(above_seconds, 1),
        "window_seconds": int(window.total_seconds()),
    }
