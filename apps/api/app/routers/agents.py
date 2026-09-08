"""Agent create / list / get / update / delete routes."""

from __future__ import annotations

from typing import Any

from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user, verify_api_key
from app.database_init import ROLE_ADMIN, ROLE_SUPER_ADMIN
from app.models.schemas import (
    AgentCreateRequest,
    AgentResponse,
    AgentUpdateRequest,
    SuccessResponse,
)
from app.services import agent_service, phone_number_service
from app.services.agent_config_validation import AgentConfigValidationError
from app.services.agent_service import AgentConflictError, AgentNotFoundError
from app.services.agent_telephony_service import AgentTelephonyError
from app.services.phone_number_service import PhoneNumberError

router = APIRouter(prefix="/agents", tags=["agents"])

_DELETE_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN})


def _require_active_org(current_user: dict[str, Any]) -> str:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organisation in token",
        )
    return str(org_id)


def _require_delete_role(current_user: dict[str, Any]) -> None:
    if current_user.get("role") not in _DELETE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete agents",
        )


def _raise_agent_validation(exc: AgentConfigValidationError) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(exc),
    ) from exc


def _raise_agent_conflict(exc: AgentConflictError) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(exc),
    ) from exc


def _raise_agent_not_found(exc: AgentNotFoundError) -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=str(exc),
    ) from exc


def _raise_agent_telephony(exc: AgentTelephonyError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.message,
    ) from exc


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Create an agent in the caller's active organisation (any member)."""
    org_id = _require_active_org(current_user)
    try:
        return await agent_service.create_agent(
            org_id,
            str(current_user["email"]),
            body,
        )
    except AgentConfigValidationError as exc:
        _raise_agent_validation(exc)
    except AgentTelephonyError as exc:
        _raise_agent_telephony(exc)
    except AgentConflictError as exc:
        _raise_agent_conflict(exc)


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List agents for the caller's active organisation."""
    org_id = _require_active_org(current_user)
    return agent_service.list_agents(org_id)


@router.get("/by-phone/{phone_number}", response_model=AgentResponse)
async def get_agent_by_phone_number(
    phone_number: str,
    _: bool = Depends(verify_api_key),
) -> dict[str, Any]:
    """Resolve agent by linked phone number (voice server; X-API-Key)."""
    decoded = unquote(phone_number)
    try:
        return phone_number_service.get_agent_by_phone(decoded)
    except PhoneNumberError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        ) from exc


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Get one agent by id (same organisation only)."""
    org_id = _require_active_org(current_user)
    try:
        return agent_service.get_agent(org_id, agent_id)
    except AgentNotFoundError as exc:
        _raise_agent_not_found(exc)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    body: AgentUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Update an agent in the caller's active organisation (any member)."""
    org_id = _require_active_org(current_user)
    try:
        return await agent_service.update_agent(org_id, agent_id, body)
    except AgentConfigValidationError as exc:
        _raise_agent_validation(exc)
    except AgentTelephonyError as exc:
        _raise_agent_telephony(exc)
    except AgentConflictError as exc:
        _raise_agent_conflict(exc)
    except AgentNotFoundError as exc:
        _raise_agent_not_found(exc)


@router.delete("/{agent_id}", response_model=SuccessResponse)
async def delete_agent(
    agent_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SuccessResponse:
    """Delete an agent (admin / super_admin only)."""
    _require_delete_role(current_user)
    org_id = _require_active_org(current_user)
    try:
        await agent_service.delete_agent(org_id, agent_id)
    except AgentNotFoundError as exc:
        _raise_agent_not_found(exc)
    return SuccessResponse(message=f"Agent deleted: {agent_id}")
