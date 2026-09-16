"""Named endpoints for connection-based providers (OpenAI-compatible LLMs)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import get_current_user
from app.database_init import ROLE_ADMIN, ROLE_SUPER_ADMIN
from app.models.schemas import (
    ProviderConnectionCreate,
    ProviderConnectionProbeRequest,
    ProviderConnectionProbeResponse,
    ProviderConnectionResponse,
    ProviderConnectionUpdate,
    SuccessResponse,
)
from app.services import provider_connection_service as connections
from app.services.secret_crypto import EncryptionNotConfiguredError

router = APIRouter(prefix="/provider-connections", tags=["provider-connections"])

# Handlers are declared sync on purpose: they do blocking work (pymongo, and a
# probe that waits on an operator-supplied host for up to
# PROVIDER_CONNECTION_PROBE_TIMEOUT). FastAPI runs a sync handler in a worker
# thread, so a slow endpoint cannot stall every other in-flight request.

_WRITE_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN})


def _require_write_role(current_user: dict[str, Any]) -> None:
    if current_user.get("role") not in _WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can manage provider connections",
        )


def _org_id(current_user: dict[str, Any]) -> str:
    org_id = str(current_user.get("org_id") or "").strip()
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organisation for user",
        )
    return org_id


def _http_error(exc: Exception) -> None:
    if isinstance(exc, connections.ProviderConnectionNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if isinstance(exc, connections.ProviderConnectionConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if isinstance(exc, connections.ProviderConnectionInUseError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if isinstance(exc, EncryptionNotConfiguredError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.get("", response_model=list[ProviderConnectionResponse])
def list_connections(
    provider: str | None = Query(default=None),
    enabled_only: bool = Query(default=False),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Connections for the caller's organisation, keys masked."""
    return connections.list_connections(
        _org_id(current_user), provider=provider, enabled_only=enabled_only
    )


@router.post(
    "",
    response_model=ProviderConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_connection(
    body: ProviderConnectionCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Add a named endpoint (admin / super_admin)."""
    _require_write_role(current_user)
    try:
        return connections.create_connection(
            _org_id(current_user),
            body.model_dump(),
            created_by=str(current_user.get("email") or "") or None,
        )
    except Exception as exc:
        _http_error(exc)
        raise


@router.post("/probe", response_model=ProviderConnectionProbeResponse)
def probe_connection(
    body: ProviderConnectionProbeRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Test an endpoint before saving it — lists the models it serves."""
    _require_write_role(current_user)
    return connections.probe_endpoint(body.base_url, body.api_key, model=body.model)


@router.get("/{connection_id}", response_model=ProviderConnectionResponse)
def get_connection(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """One connection, key masked."""
    try:
        return connections.get_connection(_org_id(current_user), connection_id)
    except Exception as exc:
        _http_error(exc)
        raise


@router.patch("/{connection_id}", response_model=ProviderConnectionResponse)
def update_connection(
    connection_id: str,
    body: ProviderConnectionUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Patch a connection (admin / super_admin)."""
    _require_write_role(current_user)
    try:
        return connections.update_connection(
            _org_id(current_user),
            connection_id,
            body.model_dump(exclude_unset=True),
        )
    except Exception as exc:
        _http_error(exc)
        raise


@router.delete("/{connection_id}", response_model=SuccessResponse)
def delete_connection(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SuccessResponse:
    """Delete a connection unless an agent still references it."""
    _require_write_role(current_user)
    try:
        deleted = connections.delete_connection(_org_id(current_user), connection_id)
    except Exception as exc:
        _http_error(exc)
        raise
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider connection not found: {connection_id}",
        )
    return SuccessResponse(message=f"Provider connection deleted: {connection_id}")


@router.post("/{connection_id}/test", response_model=ProviderConnectionProbeResponse)
def test_connection(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Probe a stored connection; caches the model list when it answers."""
    _require_write_role(current_user)
    try:
        return connections.probe_and_record(_org_id(current_user), connection_id)
    except Exception as exc:
        _http_error(exc)
        raise


@router.get("/{connection_id}/resolved", response_model=dict)
def resolved_connection(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Decrypted endpoint + key for the runtime's bot token at call setup.

    Admin-gated like ``GET /auth/{provider}`` unmasked: the runtime's bot token
    carries the admin role, a member's does not.
    """
    _require_write_role(current_user)
    try:
        return connections.resolve_auth(_org_id(current_user), connection_id)
    except Exception as exc:
        _http_error(exc)
        raise
