"""Phone number inventory, attach/detach, and provider inventory routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.models.schemas import (
    PhoneNumberAttachRequest,
    PhoneNumberDetachRequest,
    PhoneNumberInventoryResponse,
    PhoneNumberResponse,
    SuccessResponse,
)
from app.services import agent_telephony_service, phone_number_service
from app.services.agent_telephony_service import AgentTelephonyError
from app.services.phone_number_service import PhoneNumberError, PhoneNumberNotFoundError

router = APIRouter(prefix="/phone-numbers", tags=["phone-numbers"])


def _require_active_org(current_user: dict[str, Any]) -> str:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organisation in token",
        )
    return str(org_id)


def _raise_phone_error(exc: PhoneNumberError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.message,
    ) from exc


def _raise_telephony(exc: AgentTelephonyError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.message,
    ) from exc


def _validate_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in agent_telephony_service.supported_providers():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported telephony provider: {provider}",
        )
    return normalized


@router.get("", response_model=list[PhoneNumberResponse])
async def list_phone_numbers(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List phone numbers in the caller's active organisation inventory."""
    org_id = _require_active_org(current_user)
    return phone_number_service.list_by_org(org_id)


@router.get("/agent/{agent_id}", response_model=PhoneNumberResponse)
async def get_phone_number_by_agent(
    agent_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Get the phone number attached to an agent."""
    org_id = _require_active_org(current_user)
    try:
        return phone_number_service.get_by_agent(org_id, agent_id)
    except PhoneNumberError as exc:
        _raise_phone_error(exc)


@router.post(
    "/attach",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
)
async def attach_phone_number(
    body: PhoneNumberAttachRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Add to inventory and optionally attach to an agent (provider link included)."""
    org_id = _require_active_org(current_user)
    try:
        return await phone_number_service.attach(
            org_id,
            body.phone_number,
            body.provider,
            agent_id=body.agent_id,
            member_email=current_user.get("email"),
        )
    except PhoneNumberError as exc:
        _raise_phone_error(exc)
    except AgentTelephonyError as exc:
        _raise_telephony(exc)


@router.delete("/detach", response_model=SuccessResponse)
async def detach_phone_number(
    body: PhoneNumberDetachRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Detach from agent and unlink at the telephony provider."""
    org_id = _require_active_org(current_user)
    try:
        return await phone_number_service.detach(
            org_id,
            body.phone_number,
            member_email=current_user.get("email"),
        )
    except PhoneNumberError as exc:
        _raise_phone_error(exc)
    except AgentTelephonyError as exc:
        _raise_telephony(exc)


@router.get(
    "/providers/{provider}/inventory",
    response_model=PhoneNumberInventoryResponse,
)
async def list_provider_inventory(
    provider: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> PhoneNumberInventoryResponse:
    """List numbers on the org's telephony provider account."""
    org_id = _require_active_org(current_user)
    provider = _validate_provider(provider)
    try:
        numbers = await agent_telephony_service.list_provider_numbers(org_id, provider)
    except AgentTelephonyError as exc:
        _raise_telephony(exc)
    return PhoneNumberInventoryResponse(numbers=numbers)
