"""SLA analytics routes — campaign-scoped metrics and deployment-wide GPU / telephony."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.services.sla.availability import collect_availability
from app.services.sla.base_details import collect_base_details
from app.services.sla.campaign_scope import CampaignNotFoundError
from app.services.sla.gpu import collect_gpu
from app.services.sla.incidents import collect_incidents
from app.services.sla.telephony import collect_telephony
from app.services.sla.telemetry import (
    collect_capacity,
    collect_inference,
    collect_orchestration,
    collect_telemetry,
)

router = APIRouter(prefix="/sla", tags=["sla"])


def _require_active_org(current_user: dict[str, Any]) -> str:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organisation in token",
        )
    return str(org_id)


def _raise_campaign_not_found(exc: CampaignNotFoundError) -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=str(exc),
    ) from exc


# ---------------------------------------------------------------------------
# Base details (overview)
# ---------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/base-details")
async def get_base_details(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Overview cards with status, active_since / down_since, and duration."""
    org_id = _require_active_org(current_user)
    try:
        return collect_base_details(org_id, campaign_id)
    except CampaignNotFoundError as exc:
        _raise_campaign_not_found(exc)


# ---------------------------------------------------------------------------
# GPU (deployment)
# ---------------------------------------------------------------------------


@router.get("/gpu")
async def get_gpu(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Sample nvidia-smi, store history, return agreed vs actual GPU metrics."""
    _require_active_org(current_user)
    return collect_gpu()


# ---------------------------------------------------------------------------
# Campaign telemetry / inference / orchestration / capacity
# ---------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/telemetry")
async def get_telemetry(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Aggregated calls + STT/TTS/LLM + orchestration from CallMetrics / Redis."""
    org_id = _require_active_org(current_user)
    try:
        return await collect_telemetry(org_id, campaign_id)
    except CampaignNotFoundError as exc:
        _raise_campaign_not_found(exc)


@router.get("/campaigns/{campaign_id}/inference")
async def get_inference(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """STT / TTS / LLM percentiles for one campaign."""
    org_id = _require_active_org(current_user)
    try:
        return collect_inference(org_id, campaign_id)
    except CampaignNotFoundError as exc:
        _raise_campaign_not_found(exc)


@router.get("/campaigns/{campaign_id}/orchestration")
async def get_orchestration(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """End-to-end latency and session-start for one campaign."""
    org_id = _require_active_org(current_user)
    try:
        return collect_orchestration(org_id, campaign_id)
    except CampaignNotFoundError as exc:
        _raise_campaign_not_found(exc)


@router.get("/campaigns/{campaign_id}/capacity")
async def get_capacity(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Live and peak call capacity for one campaign."""
    org_id = _require_active_org(current_user)
    try:
        return await collect_capacity(org_id, campaign_id)
    except CampaignNotFoundError as exc:
        _raise_campaign_not_found(exc)


# ---------------------------------------------------------------------------
# Deployment availability / telephony / incidents
# ---------------------------------------------------------------------------


@router.get("/availability")
async def get_availability(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Uptime targets. Actuals are null until health history exists."""
    _require_active_org(current_user)
    return collect_availability()


@router.get("/telephony")
async def get_telephony(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Telephony SLA metrics from the provider contract, when configured."""
    _require_active_org(current_user)
    return collect_telephony()


@router.get("/incidents")
async def get_incidents(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Incident-handling targets. Actuals are null without an incident store."""
    _require_active_org(current_user)
    return collect_incidents()
