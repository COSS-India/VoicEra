"""Campaign STT / TTS / LLM latency percentiles from CallMetrics."""

from __future__ import annotations

from typing import Any

from app.services.call_metrics_service import _entry_stage
from app.services.sla import targets
from app.services.sla.campaign_scope import (
    campaign_call_ids,
    list_campaign_calls,
    list_campaign_metrics,
    load_campaign,
)
from app.services.sla.gateway_health import fetch_gateway_health, slot_view
from app.services.sla.metrics import metric, nearest_rank_percentile, no_data_metric
from app.services.sla.status_rules import threshold_operating


def _stage_samples_ms(metrics_docs: list[dict[str, Any]], stage: str) -> list[float]:
    samples: list[float] = []
    for doc in metrics_docs:
        for breakdown in (doc.get("latencies") or {}).get("breakdowns") or []:
            if breakdown.get("user_turn_start_time") is None:
                continue
            for entry in breakdown.get("ttfb") or []:
                if _entry_stage(entry) != stage:
                    continue
                duration = entry.get("duration_secs")
                if duration is None:
                    continue
                samples.append(float(duration) * 1000.0)
    return samples


def _percentile_pair(
    samples: list[float],
) -> tuple[float | None, float | None]:
    return (
        nearest_rank_percentile(samples, 0.50),
        nearest_rank_percentile(samples, 0.95),
    )


def collect_inference(org_id: str, campaign_id: str) -> dict[str, Any]:
    campaign = load_campaign(org_id, campaign_id)
    calls = list_campaign_calls(org_id, campaign_id)
    metrics_docs = list_campaign_metrics(org_id, campaign_call_ids(calls))
    health = fetch_gateway_health()

    stt = _stage_samples_ms(metrics_docs, "stt")
    tts = _stage_samples_ms(metrics_docs, "tts")
    llm = _stage_samples_ms(metrics_docs, "llm")
    stt_p50, stt_p95 = _percentile_pair(stt)
    tts_p50, tts_p95 = _percentile_pair(tts)
    llm_p50, llm_p95 = _percentile_pair(llm)

    source = "call_metrics" if metrics_docs else "no_samples"
    metrics = [
        metric(
            key="stt_p50",
            label="Speech to text, p50",
            target=targets.STT_P50_MS,
            comparator="lte",
            unit="ms",
            actual=stt_p50,
            source=source,
            scope="campaign",
            sample_count=len(stt),
        ),
        metric(
            key="stt_p95",
            label="Speech to text, p95",
            target=targets.STT_P95_MS,
            comparator="lte",
            unit="ms",
            actual=stt_p95,
            source=source,
            scope="campaign",
            sample_count=len(stt),
        ),
        metric(
            key="tts_p50",
            label="Text to speech first audio, p50",
            target=targets.TTS_P50_MS,
            comparator="lte",
            unit="ms",
            actual=tts_p50,
            source=source,
            scope="campaign",
            sample_count=len(tts),
        ),
        metric(
            key="tts_p95",
            label="Text to speech first audio, p95",
            target=targets.TTS_P95_MS,
            comparator="lte",
            unit="ms",
            actual=tts_p95,
            source=source,
            scope="campaign",
            sample_count=len(tts),
        ),
        metric(
            key="llm_p50",
            label="Language model first token, p50",
            target=targets.LLM_P50_MS,
            comparator="lte",
            unit="ms",
            actual=llm_p50,
            source=source,
            scope="campaign",
            sample_count=len(llm),
        ),
        metric(
            key="llm_p95",
            label="Language model first token, p95",
            target=targets.LLM_P95_MS,
            comparator="lte",
            unit="ms",
            actual=llm_p95,
            source=source,
            scope="campaign",
            sample_count=len(llm),
        ),
        no_data_metric(
            key="error_rate",
            label="Error rate",
            target=targets.ERROR_RATE_PCT,
            comparator="lte",
            unit="pct",
            source="not_persisted",
            scope="campaign",
        ),
        no_data_metric(
            key="timeout_rate",
            label="Timeout rate",
            target=targets.TIMEOUT_RATE_PCT,
            comparator="lte",
            unit="pct",
            source="not_persisted",
            scope="campaign",
        ),
        no_data_metric(
            key="llm_output_speed",
            label="Language model output speed",
            target=targets.LLM_TOKENS_PER_SEC,
            comparator="gte",
            unit="tokens_per_s",
            source="usage_metrics_disabled",
            scope="campaign",
        ),
    ]
    # Stamp operating_status on error rows explicitly (already unknown via no_data).
    for row in metrics:
        if row["key"] in {"error_rate", "timeout_rate", "llm_output_speed"}:
            row["operating_status"] = threshold_operating(
                row["actual"], target=row["target"], comparator=row["comparator"]
            )

    slots = {
        name: slot_view(health, name) for name in ("stt", "tts", "llm")
    }
    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign.get("name"),
        "scope": "campaign",
        "call_count": len(calls),
        "metrics_document_count": len(metrics_docs),
        "gateway": {
            "scope": "deployment",
            "configured": health.get("configured"),
            "reachable": health.get("reachable"),
            "slots": slots,
            "reason": health.get("reason"),
        },
        "metrics": metrics,
    }
