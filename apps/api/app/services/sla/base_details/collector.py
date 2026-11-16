"""Overview cards: servers, phone lines, STT/LLM/TTS, orchestrator with since/duration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.sla.base_details.component_state import (
    duration_seconds,
    upsert_component_state,
)
from app.services.sla.campaign_scope import (
    campaign_call_ids,
    list_campaign_calls,
    list_campaign_metrics,
    load_campaign,
)
from app.services.sla.gateway_health import fetch_gateway_health, model_server_base_url
from app.services.sla.gpu import run_nvidia_smi
from app.services.sla.status_rules import (
    SERVICE_LABELS,
    hosting_status,
    orchestrator_status,
    telephony_status,
)
from app.services.sla.telemetry.orchestration import session_start_rate
from app.services.sla.telephony import provider_components_up, telephony_configured

_STATUS_MAP = {
    "working_normally": "working",
    "not_working_normally": "not_working",
    "unknown": "unknown",
}


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


def _call_activity_stamp(call: dict[str, Any]) -> datetime | None:
    """Best timestamp for when this call was active."""
    for key in ("end_time_utc", "updated_at", "start_time_utc", "created_at"):
        stamp = _parse_iso(call.get(key))
        if stamp is not None:
            return stamp
    return None


def _format_ago(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _campaign_call_activity(
    calls: list[dict[str, Any]], now: datetime
) -> dict[str, Any]:
    """Running if any call is in progress; otherwise how long ago the last call was."""
    live = [c for c in calls if c.get("status") == "in_progress"]
    if live:
        started = None
        for call in live:
            stamp = _parse_iso(call.get("start_time_utc") or call.get("created_at"))
            if stamp and (started is None or stamp < started):
                started = stamp
        ago = duration_seconds(started.isoformat(), now) if started else 0
        return {
            "status": "running",
            "last_call_at": started.isoformat() if started else None,
            "call_happened_ago_seconds": ago,
            "call_happened": "in progress",
        }

    last_stamp: datetime | None = None
    for call in calls:
        stamp = _call_activity_stamp(call)
        if stamp and (last_stamp is None or stamp > last_stamp):
            last_stamp = stamp

    if last_stamp is None:
        return {
            "status": "not_running",
            "last_call_at": None,
            "call_happened_ago_seconds": None,
            "call_happened": "no calls yet",
        }

    ago = duration_seconds(last_stamp.isoformat(), now) or 0
    return {
        "status": "not_running",
        "last_call_at": last_stamp.isoformat(),
        "call_happened_ago_seconds": ago,
        "call_happened": f"call happened: {_format_ago(ago)}",
    }


def _pipeline_last_active(
    calls: list[dict[str, Any]], metrics_docs: list[dict[str, Any]]
) -> str | None:
    candidates: list[datetime] = []
    for call in calls:
        if call.get("status") == "in_progress":
            stamp = _parse_iso(call.get("updated_at") or call.get("start_time_utc"))
            if stamp:
                candidates.append(stamp)
    for doc in metrics_docs:
        stamp = _parse_iso(doc.get("recorded_at"))
        if stamp:
            candidates.append(stamp)
    if not candidates:
        return None
    return max(candidates).isoformat()


def _service_card(
    *,
    service_id: str,
    scope: str,
    operating_status: str,
    org_id: str | None,
    campaign_id: str | None,
    now: datetime,
    rule: str,
) -> dict[str, Any]:
    status = _STATUS_MAP.get(operating_status, "unknown")
    try:
        state = upsert_component_state(
            component_id=service_id,
            scope=scope,
            status=status,
            org_id=org_id,
            campaign_id=campaign_id if scope == "campaign" else None,
        )
        since = state.get("since")
    except Exception:
        since = now.isoformat()

    active_since = since if status == "working" else None
    down_since = since if status == "not_working" else None
    dur = duration_seconds(since, now) if status in {"working", "not_working"} else None

    return {
        "id": service_id,
        "label": SERVICE_LABELS[service_id],
        "scope": scope,
        "status": status,
        "operating_status": operating_status,
        "active_since": active_since,
        "down_since": down_since,
        "duration_seconds": dur,
        "rule": rule,
    }


def collect_base_details(org_id: str, campaign_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    campaign = load_campaign(org_id, campaign_id)
    calls = list_campaign_calls(org_id, campaign_id)
    metrics_docs = list_campaign_metrics(org_id, campaign_call_ids(calls))
    metrics_by_call = {str(d.get("call_id")): d for d in metrics_docs}

    gpu = run_nvidia_smi()
    health = fetch_gateway_health()
    model_configured = bool(model_server_base_url())

    hosting_op = hosting_status(
        nvidia_smi_available=bool(gpu.get("available")),
        gpu_count=len(gpu.get("gpus") or []),
        nvidia_smi_failed=bool(gpu.get("failed")),
        model_server_configured=model_configured,
        gateway_reachable=health.get("reachable"),
    )
    telephony_op = telephony_status(
        configured=telephony_configured(),
        components_up=provider_components_up(),
    )

    activity = _campaign_call_activity(calls, now)
    stage_cards = []
    for service_id in ("stt", "llm", "tts"):
        try:
            state = upsert_component_state(
                component_id=service_id,
                scope="campaign",
                status=activity["status"],
                org_id=org_id,
                campaign_id=campaign_id,
            )
            since = state.get("since")
        except Exception:
            since = now.isoformat()
        stage_cards.append(
            {
                "id": service_id,
                "label": SERVICE_LABELS[service_id],
                "scope": "campaign",
                "status": activity["status"],
                "active_since": since if activity["status"] == "running" else None,
                "down_since": None,
                "duration_seconds": (
                    duration_seconds(since, now)
                    if activity["status"] == "running"
                    else activity["call_happened_ago_seconds"]
                ),
                "last_call_at": activity["last_call_at"],
                "call_happened_ago_seconds": activity["call_happened_ago_seconds"],
                "call_happened": activity["call_happened"],
                "rule": (
                    "running while a campaign call is in_progress; otherwise "
                    "not_running with how long ago the last campaign call was"
                ),
            }
        )

    orch_op = orchestrator_status(calls=calls, metrics_by_call_id=metrics_by_call)

    services = [
        _service_card(
            service_id="hosting",
            scope="deployment",
            operating_status=hosting_op,
            org_id=org_id,
            campaign_id=None,
            now=now,
            rule="nvidia-smi sees a GPU; gateway /health answers when MODEL_SERVER_URL is set",
        ),
        _service_card(
            service_id="telephony",
            scope="deployment",
            operating_status=telephony_op,
            org_id=org_id,
            campaign_id=None,
            now=now,
            rule="provider availability says websocket, number, and gateway are up",
        ),
        *stage_cards,
        _service_card(
            service_id="orchestrator",
            scope="campaign",
            operating_status=orch_op,
            org_id=org_id,
            campaign_id=campaign_id,
            now=now,
            rule=(
                "campaign call in_progress, or latest answered call reached the "
                "pipeline with CallMetrics"
            ),
        ),
    ]

    start_rate = session_start_rate(calls)
    critical_down = [
        s["id"]
        for s in services
        if s["id"] in {"hosting", "stt", "llm", "tts"} and s["status"] == "not_working"
    ]
    session_failing = start_rate is not None and start_rate < 50.0 and len(calls) > 0
    summary: dict[str, Any] | None = None
    if critical_down or session_failing:
        affected = list(critical_down)
        if session_failing and "orchestrator" not in affected:
            affected.append("orchestrator")
        started_candidates = [
            _parse_iso(s.get("down_since"))
            for s in services
            if s["status"] == "not_working" and s.get("down_since")
        ]
        started_candidates = [s for s in started_candidates if s is not None]
        started_at = min(started_candidates) if started_candidates else now
        summary = {
            "affected_services": affected,
            "started_at": started_at.isoformat(),
            "next_update_at": (started_at + timedelta(minutes=15)).isoformat(),
            "expected_fix_by": (started_at + timedelta(hours=2)).isoformat(),
            "session_start_pct": start_rate,
        }

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign.get("name"),
        "pipeline_last_active_at": _pipeline_last_active(calls, metrics_docs),
        "services": services,
        "summary": summary,
    }
