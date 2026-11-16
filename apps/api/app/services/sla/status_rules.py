"""Operating-status rules shared by base-details and error metrics."""

from __future__ import annotations

from typing import Any, Literal

OperatingStatus = Literal["working_normally", "not_working_normally", "unknown"]

SERVICE_IDS = (
    "hosting",
    "telephony",
    "stt",
    "llm",
    "tts",
    "orchestrator",
)

SERVICE_LABELS = {
    "hosting": "Servers (hosting)",
    "telephony": "Phone lines (telephony)",
    "stt": "Listening (STT)",
    "llm": "Understanding (LLM)",
    "tts": "Speaking (TTS)",
    "orchestrator": "Orchestrator",
}


def hosting_status(
    *,
    nvidia_smi_available: bool,
    gpu_count: int | None,
    nvidia_smi_failed: bool,
    model_server_configured: bool,
    gateway_reachable: bool | None,
) -> OperatingStatus:
    if nvidia_smi_failed:
        return "not_working_normally"
    if not nvidia_smi_available and not model_server_configured:
        return "unknown"
    if nvidia_smi_available and (gpu_count or 0) <= 0:
        return "not_working_normally"
    if model_server_configured and gateway_reachable is False:
        return "not_working_normally"
    if nvidia_smi_available and (gpu_count or 0) > 0:
        if not model_server_configured or gateway_reachable is True:
            return "working_normally"
    if model_server_configured and gateway_reachable is True:
        return "working_normally"
    return "unknown"


def telephony_status(*, configured: bool, components_up: bool | None) -> OperatingStatus:
    if not configured:
        return "unknown"
    if components_up is None:
        return "unknown"
    return "working_normally" if components_up else "not_working_normally"


def slot_status(
    *,
    model_server_configured: bool,
    slot: dict[str, Any] | None,
    latest_has_stage_sample: bool | None,
) -> OperatingStatus:
    """STT / LLM / TTS card status.

    ``latest_has_stage_sample`` is None when the campaign has no metrics yet.
    """
    deployed = bool(slot and slot.get("deployed"))
    reachable = bool(slot and slot.get("reachable"))

    if not model_server_configured:
        if latest_has_stage_sample is True:
            return "working_normally"
        if latest_has_stage_sample is False:
            return "not_working_normally"
        return "unknown"

    if not deployed:
        if latest_has_stage_sample is True:
            return "working_normally"
        return "unknown"

    if not reachable:
        return "not_working_normally"

    if latest_has_stage_sample is False:
        return "not_working_normally"
    return "working_normally"


def orchestrator_status(
    *,
    calls: list[dict[str, Any]],
    metrics_by_call_id: dict[str, dict[str, Any]],
) -> OperatingStatus:
    if not calls:
        return "unknown"
    if any(c.get("status") == "in_progress" for c in calls):
        return "working_normally"

    answered = [
        c
        for c in calls
        if c.get("call_response") == "answered"
        or c.get("status") in {"in_progress", "completed", "failed"}
    ]
    if not answered:
        return "unknown"

    latest = answered[0]
    call_id = str(latest.get("call_id") or "")
    status = latest.get("status")
    has_metrics = call_id in metrics_by_call_id

    if status in {"in_progress", "completed"} and has_metrics:
        return "working_normally"
    if status == "failed" and not has_metrics:
        return "not_working_normally"
    if status not in {"in_progress", "completed"} and not has_metrics:
        return "not_working_normally"
    if status in {"in_progress", "completed"}:
        return "working_normally"
    return "not_working_normally"


def threshold_operating(
    actual: float | None,
    *,
    target: float,
    comparator: str,
) -> OperatingStatus:
    if actual is None:
        return "unknown"
    if comparator in {"lte", "or_less", "<="}:
        return "working_normally" if actual <= target else "not_working_normally"
    if comparator in {"gte", "or_more", ">="}:
        return "working_normally" if actual >= target else "not_working_normally"
    return "unknown"
