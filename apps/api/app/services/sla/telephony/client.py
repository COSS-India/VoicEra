"""Telephony SLA metrics from the provider contract, when configured."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.services.sla import targets
from app.services.sla.metrics import metric, no_data_metric
from app.services.sla.status_rules import threshold_operating

logger = logging.getLogger(__name__)


def telephony_configured() -> bool:
    return bool(
        (os.getenv("TELEPHONY_SLA_BASE_URL") or "").strip()
        and (os.getenv("TELEPHONY_SLA_TOKEN") or "").strip()
    )


def _provider_get(path: str) -> dict[str, Any] | None:
    base = (os.getenv("TELEPHONY_SLA_BASE_URL") or "").strip().rstrip("/")
    token = (os.getenv("TELEPHONY_SLA_TOKEN") or "").strip()
    if not base or not token:
        return None
    url = f"{base}{path}"
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        response.raise_for_status()
        body = response.json()
        return body if isinstance(body, dict) else None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Telephony SLA fetch %s failed: %s", path, exc)
        return None


def _num(payload: dict[str, Any] | None, *keys: str) -> float | None:
    if not payload:
        return None
    cur: Any = payload
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    if cur is None:
        return None
    try:
        return float(cur)
    except (TypeError, ValueError):
        return None


def provider_components_up() -> bool | None:
    """True when websocket, number, and gateway are all up. None if unconfigured."""
    if not telephony_configured():
        return None
    payload = _provider_get("/v1/availability")
    if payload is None:
        return None
    for key in ("websocket_up", "number_up", "gateway_up"):
        if key in payload and payload[key] is False:
            return False
    status = payload.get("status")
    if status == "down":
        return False
    if status == "up":
        return True
    if all(payload.get(k) is True for k in ("websocket_up", "number_up", "gateway_up")):
        return True
    return None


def collect_telephony() -> dict[str, Any]:
    if not telephony_configured():
        metrics = [
            no_data_metric(
                key=key,
                label=label,
                target=target,
                comparator=comparator,
                unit=unit,
                source="telephony_unconfigured",
                scope="deployment",
            )
            for key, label, target, comparator, unit in _TELEPHONY_ROWS
        ]
        for row in metrics:
            row["operating_status"] = "unknown"
        return {
            "scope": "deployment",
            "source": "telephony_unconfigured",
            "configured": False,
            "metrics": metrics,
        }

    availability = _provider_get("/v1/availability") or {}
    capacity = _provider_get("/v1/capacity") or {}
    # Media / quality aggregates may live on availability or a summary object.
    quality = _provider_get("/v1/media") or {}
    if "summary" in quality and isinstance(quality["summary"], dict):
        quality = quality["summary"]

    values = {
        "telephony_availability": _num(availability, "availability_pct"),
        "telephony_peak_hours_availability": _num(
            availability, "peak_hours_availability_pct"
        ),
        "call_setup_success": _num(availability, "call_setup_success_pct")
        or _num(quality, "call_setup_success_pct"),
        "post_dial_delay_p95": _num(quality, "post_dial_delay_p95_s"),
        "connection_time_p95": _num(quality, "connection_time_p95_ms"),
        "one_way_media_delay": _num(quality, "one_way_media_delay_ms"),
        "jitter": _num(quality, "jitter_ms"),
        "packet_loss": _num(quality, "packet_loss_pct"),
        "audio_quality_mos": _num(quality, "mos"),
        "carrier_side_call_drops": _num(quality, "carrier_side_call_drops_pct"),
        "telephony_connections_reserved": _num(capacity, "reserved_connections"),
    }

    metrics: list[dict[str, Any]] = []
    for key, label, target, comparator, unit in _TELEPHONY_ROWS:
        actual = values.get(key)
        row = metric(
            key=key,
            label=label,
            target=target,
            comparator=comparator,
            unit=unit,
            actual=actual,
            source="telephony_provider" if actual is not None else "provider_missing_field",
            scope="deployment",
            operating_status=threshold_operating(
                actual, target=target, comparator=comparator
            ),
        )
        metrics.append(row)

    return {
        "scope": "deployment",
        "source": "telephony_provider",
        "configured": True,
        "components_up": provider_components_up(),
        "metrics": metrics,
    }


_TELEPHONY_ROWS: list[tuple[str, str, float, str, str]] = [
    (
        "telephony_availability",
        "Telephony availability",
        targets.TELEPHONY_AVAILABILITY_PCT,
        "gte",
        "pct",
    ),
    (
        "telephony_peak_hours_availability",
        "Telephony peak-hours availability",
        targets.TELEPHONY_PEAK_AVAILABILITY_PCT,
        "gte",
        "pct",
    ),
    (
        "call_setup_success",
        "Call setup success",
        targets.CALL_SETUP_SUCCESS_PCT,
        "gte",
        "pct",
    ),
    (
        "post_dial_delay_p95",
        "Post-dial delay, p95",
        targets.POST_DIAL_DELAY_P95_S,
        "lte",
        "s",
    ),
    (
        "connection_time_p95",
        "Connection time, p95",
        targets.CONNECTION_TIME_P95_MS,
        "lte",
        "ms",
    ),
    (
        "one_way_media_delay",
        "One-way media delay",
        targets.ONE_WAY_MEDIA_MS,
        "lte",
        "ms",
    ),
    ("jitter", "Jitter", targets.JITTER_MS, "lte", "ms"),
    ("packet_loss", "Packet loss", targets.PACKET_LOSS_PCT, "lte", "pct"),
    ("audio_quality_mos", "Audio quality (MOS)", targets.MOS_MIN, "gte", "mos"),
    (
        "carrier_side_call_drops",
        "Carrier-side call drops",
        targets.CARRIER_DROPS_PCT,
        "lte",
        "pct",
    ),
    (
        "telephony_connections_reserved",
        "Telephony connections reserved",
        float(targets.COMMITTED_CAPACITY),
        "gte",
        "calls",
    ),
]
