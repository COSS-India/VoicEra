"""Campaign telemetry aggregate: capacity + STT/TTS/LLM from CallMetrics."""

from __future__ import annotations

from typing import Any

from app.services.sla.telemetry.capacity import collect_capacity
from app.services.sla.telemetry.inference import collect_inference
from app.services.sla.telemetry.orchestration import collect_orchestration


async def collect_telemetry(org_id: str, campaign_id: str) -> dict[str, Any]:
    """One payload for the Performance view: calls + pipeline timings."""
    inference = collect_inference(org_id, campaign_id)
    orchestration = collect_orchestration(org_id, campaign_id)
    capacity = await collect_capacity(org_id, campaign_id)

    return {
        "campaign_id": campaign_id,
        "campaign_name": inference.get("campaign_name")
        or capacity.get("campaign_name"),
        "scope": "campaign",
        "call_count": capacity.get("call_count") or inference.get("call_count") or 0,
        "capacity": {
            "metrics": capacity.get("metrics") or [],
        },
        "inference": {
            "metrics": inference.get("metrics") or [],
            "gateway": inference.get("gateway"),
        },
        "orchestration": {
            "metrics": orchestration.get("metrics") or [],
        },
        "metrics": [
            *(capacity.get("metrics") or []),
            *(inference.get("metrics") or []),
            *(orchestration.get("metrics") or []),
        ],
    }
