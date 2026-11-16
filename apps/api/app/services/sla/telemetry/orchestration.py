"""Campaign orchestration latency and session-start metrics."""

from __future__ import annotations

from typing import Any

from app.services.sla import targets
from app.services.sla.campaign_scope import (
    campaign_call_ids,
    list_campaign_calls,
    list_campaign_metrics,
    load_campaign,
)
from app.services.sla.metrics import metric, nearest_rank_percentile, no_data_metric
from app.services.sla.status_rules import threshold_operating


def _user_bot_latencies_ms(metrics_docs: list[dict[str, Any]]) -> list[float]:
    samples: list[float] = []
    for doc in metrics_docs:
        for value in (doc.get("latencies") or {}).get("user_to_bot_secs") or []:
            samples.append(float(value) * 1000.0)
    return samples


def session_start_rate(calls: list[dict[str, Any]]) -> float | None:
    if not calls:
        return None
    started = sum(
        1 for c in calls if c.get("status") in {"in_progress", "completed"}
    )
    return round((started / len(calls)) * 100.0, 2)


def collect_orchestration(org_id: str, campaign_id: str) -> dict[str, Any]:
    campaign = load_campaign(org_id, campaign_id)
    calls = list_campaign_calls(org_id, campaign_id)
    metrics_docs = list_campaign_metrics(org_id, campaign_call_ids(calls))
    latencies = _user_bot_latencies_ms(metrics_docs)
    p50 = nearest_rank_percentile(latencies, 0.50)
    p95 = nearest_rank_percentile(latencies, 0.95)
    source = "call_metrics" if latencies else "no_samples"
    start_rate = session_start_rate(calls)

    metrics = [
        no_data_metric(
            key="orchestration_overhead_p95",
            label="Orchestration overhead, p95",
            target=targets.ORCHESTRATION_OVERHEAD_P95_MS,
            comparator="lte",
            unit="ms",
            source="not_instrumented",
            scope="campaign",
        ),
        metric(
            key="end_to_end_p50",
            label="End to end, p50",
            target=targets.END_TO_END_P50_MS,
            comparator="lte",
            unit="ms",
            actual=p50,
            source=source,
            scope="campaign",
            sample_count=len(latencies),
        ),
        metric(
            key="end_to_end_p95",
            label="End to end, p95",
            target=targets.END_TO_END_P95_MS,
            comparator="lte",
            unit="ms",
            actual=p95,
            source=source,
            scope="campaign",
            sample_count=len(latencies),
        ),
        metric(
            key="agent_session_start_success",
            label="Agent session start success",
            target=targets.SESSION_START_PCT,
            comparator="gte",
            unit="pct",
            actual=start_rate,
            source="call_logs" if calls else "no_calls",
            scope="campaign",
            sample_count=len(calls),
            operating_status=threshold_operating(
                start_rate, target=targets.SESSION_START_PCT, comparator="gte"
            ),
        ),
        no_data_metric(
            key="unexpected_call_drops",
            label="Unexpected call drops",
            target=targets.UNEXPECTED_DROPS_PCT,
            comparator="lte",
            unit="pct",
            source="platform_fault_not_persisted",
            scope="campaign",
        ),
    ]
    for row in metrics:
        if row["key"] == "unexpected_call_drops":
            row["operating_status"] = "unknown"

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign.get("name"),
        "scope": "campaign",
        "call_count": len(calls),
        "metrics": metrics,
    }
