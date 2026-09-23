"""Provider-level auth catalog and credential persistence routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import get_current_user, verify_api_key
from app.database_init import ROLE_ADMIN, ROLE_SUPER_ADMIN
from app.models.schemas import (
    ProviderAuthResolved,
    ProviderAuthResponse,
    ProviderAuthUpsert,
    SuccessResponse,
)
from app.services import auth_service, platform_auth
from app.services.provider_auth_catalog import (
    UnknownAuthProviderError,
    all_auth_catalog,
    provider_auth_catalog,
)
from app.services.secret_crypto import EncryptionNotConfiguredError
from apps.providers.availability import auth_source

router = APIRouter(prefix="/auth", tags=["auth"])

_WRITE_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN})


def _require_write_role(current_user: dict[str, Any]) -> None:
    if current_user.get("role") not in _WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can manage provider credentials",
        )


def _catalog_http_error(exc: Exception) -> None:
    if isinstance(exc, UnknownAuthProviderError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    if isinstance(exc, EncryptionNotConfiguredError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    raise exc


@router.get("/catalog")
async def auth_catalog(
    _current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Provider-level auth schemas for every registered provider."""
    return all_auth_catalog()


@router.get("/catalog/{provider}")
async def auth_catalog_for_provider(
    provider: str,
    _current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Auth schema for one provider (fields merged across kinds)."""
    try:
        return provider_auth_catalog(provider)
    except Exception as exc:
        _catalog_http_error(exc)
        raise


@router.get("/configured")
async def list_configured(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[str]:
    """Provider ids that have auth stored for the caller's organisation."""
    return auth_service.list_configured_providers(current_user["org_id"])


@router.get("/availability")
async def availability(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, dict[str, Any]]:
    """Why each catalogued provider is (or is not) usable by this organisation.

    Per provider: ``source`` is what is in effect — ``"org"`` (credentials
    stored here), ``"platform"`` (supplied by the deployment), ``"local"``
    (runs on the model-server, no credential at all) or ``null``. ``provided``
    says whether it would still work with no org credentials at all.

    Both are needed, not just ``source``: an org that stores its own key on top
    of a platform-supplied provider reads as ``"org"``, and without ``provided``
    the UI cannot tell that deleting those credentials falls back rather than
    disconnects.

    Registered before ``/{provider}`` on purpose — a single-segment literal
    route must win over the parameterised one.
    """
    configured = set(auth_service.list_configured_providers(current_user["org_id"]))
    platform = platform_auth.providers()
    return {
        provider: {
            "source": auth_source(provider, configured, platform),
            # Same question asked of an org that has connected nothing.
            "provided": auth_source(provider, frozenset(), platform) is not None,
        }
        for provider in all_auth_catalog()
    }


@router.post("", response_model=ProviderAuthResponse, status_code=status.HTTP_201_CREATED)
async def upsert_auth(
    body: ProviderAuthUpsert,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Create or update stored auth for a provider (admin / super_admin)."""
    _require_write_role(current_user)
    try:
        provider_auth_catalog(body.provider)
        return auth_service.upsert_provider_auth(
            current_user["org_id"],
            body.provider,
            body.auth,
        )
    except Exception as exc:
        _catalog_http_error(exc)
        raise


@router.get("/internal/{provider}", response_model=ProviderAuthResolved)
async def resolve_auth_internal(
    provider: str,
    org_id: str = Query(..., description="Organisation the call belongs to"),
    _: bool = Depends(verify_api_key),
) -> dict[str, Any]:
    """Decrypted credentials for the voice runtime (``X-API-Key`` only).

    The single route in the API that returns a plaintext secret, and the only
    caller of the platform-credential fallback. Deliberately separate from
    ``GET /auth/{provider}``, which is always masked, so a leaked user or bot
    JWT cannot be traded for provider credentials.
    """
    try:
        provider_auth_catalog(provider)
        resolved = platform_auth.resolve(org_id, provider)
    except Exception as exc:
        _catalog_http_error(exc)
        raise

    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No auth stored for provider: {provider}",
        )

    auth, source = resolved
    return {"org_id": org_id, "provider": provider, "auth": auth, "source": source}


@router.get("/{provider}", response_model=ProviderAuthResponse)
async def get_auth(
    provider: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Stored auth for one provider, with every secret masked.

    Masked for every role, admins included: a sandbox signup is the
    ``super_admin`` of its own organisation, so role is not a boundary here.
    """
    try:
        provider_auth_catalog(provider)
    except Exception as exc:
        _catalog_http_error(exc)
        raise

    try:
        stored = auth_service.get_provider_auth_masked(
            current_user["org_id"],
            provider,
        )
    except Exception as exc:
        _catalog_http_error(exc)
        raise

    if not stored:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No auth stored for provider: {provider}",
        )
    return stored


@router.delete("/{provider}", response_model=SuccessResponse)
async def delete_auth(
    provider: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SuccessResponse:
    """Remove stored auth for a provider (admin / super_admin)."""
    _require_write_role(current_user)
    try:
        provider_auth_catalog(provider)
    except Exception as exc:
        _catalog_http_error(exc)
        raise

    deleted = auth_service.delete_provider_auth(current_user["org_id"], provider)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No auth stored for provider: {provider}",
        )
    return SuccessResponse(message=f"Auth deleted for provider: {provider}")
