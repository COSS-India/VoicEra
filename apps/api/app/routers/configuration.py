"""Configuration catalog routes (STT, TTS, LLM, telephony lists and settings)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import get_current_user
from app.services import auth_service, platform_auth
from apps.providers.availability import auth_source, is_authenticated
from apps.providers.base import Kind
from apps.providers.languages import UnknownLanguageError
from apps.providers.schema import (
    UnknownProviderError as ProviderUnknown,
    configuration_defaults,
    list_providers,
    provider_settings,
)
from apps.telephony.schema import (
    UnknownProviderError as TelephonyUnknown,
    list_providers as list_telephony_providers,
    provider_settings as telephony_provider_settings,
)

router = APIRouter(prefix="/configuration", tags=["configuration"])


def _configured_ids(org_id: str | None) -> set[str]:
    if not org_id:
        return set()
    return set(auth_service.list_configured_providers(org_id))


def _platform_ids() -> frozenset[str]:
    return platform_auth.providers()


def _with_authenticated_list(
    listed: dict[str, dict[str, Any]],
    configured: set[str],
) -> dict[str, dict[str, Any]]:
    platform = _platform_ids()
    return {
        provider: {
            **entry,
            "authenticated": is_authenticated(provider, configured, platform),
            "auth_source": auth_source(provider, configured, platform),
        }
        for provider, entry in listed.items()
    }


def _with_authenticated_entry(
    catalog: dict[str, Any],
    configured: set[str],
) -> dict[str, Any]:
    provider = str(catalog.get("provider") or "")
    platform = _platform_ids()
    return {
        **catalog,
        "authenticated": is_authenticated(provider, configured, platform),
        "auth_source": auth_source(provider, configured, platform),
    }


def _catalog_http_error(exc: Exception) -> None:
    if isinstance(exc, UnknownLanguageError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    if isinstance(exc, (ProviderUnknown, TelephonyUnknown)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    raise exc


@router.get("/stt")
async def list_stt(
    languages: str | None = Query(
        default=None,
        description="Comma-separated canonical language ids (AND filter).",
    ),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        listed = list_providers(Kind.STT, languages)
    except Exception as exc:
        _catalog_http_error(exc)
        raise
    return _with_authenticated_list(
        listed, _configured_ids(current_user.get("org_id"))
    )


@router.get("/tts")
async def list_tts(
    languages: str | None = Query(
        default=None,
        description="Comma-separated canonical language ids (AND filter).",
    ),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        listed = list_providers(Kind.TTS, languages)
    except Exception as exc:
        _catalog_http_error(exc)
        raise
    return _with_authenticated_list(
        listed, _configured_ids(current_user.get("org_id"))
    )


@router.get("/llm")
async def list_llm(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    return _with_authenticated_list(
        list_providers(Kind.LLM),
        _configured_ids(current_user.get("org_id")),
    )


@router.get("/telephony")
async def list_telephony(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    return _with_authenticated_list(
        list_telephony_providers(),
        _configured_ids(current_user.get("org_id")),
    )


@router.get("/defaults")
async def defaults(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Per-kind catalogs, the default provider picks, languages, and availability.

    The default picks come from ``DEFAULT_SERVICE_PROVIDERS`` in the provider
    registry, so the UI cannot drift from what is actually registered.
    """
    configured = _configured_ids(current_user.get("org_id"))
    platform = _platform_ids()
    envelope = configuration_defaults()
    envelope["auth_sources"] = {
        provider: auth_source(provider, configured, platform)
        for kind in (Kind.STT.value, Kind.TTS.value, Kind.LLM.value)
        for provider in envelope.get(kind, {})
    }
    return envelope


@router.get("/stt/setting/{provider}")
async def stt_settings(
    provider: str,
    languages: str | None = Query(default=None),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        catalog = provider_settings(Kind.STT, provider, languages)
    except Exception as exc:
        _catalog_http_error(exc)
        raise
    return _with_authenticated_entry(
        catalog, _configured_ids(current_user.get("org_id"))
    )


@router.get("/tts/setting/{provider}")
async def tts_settings(
    provider: str,
    languages: str | None = Query(default=None),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        catalog = provider_settings(Kind.TTS, provider, languages)
    except Exception as exc:
        _catalog_http_error(exc)
        raise
    return _with_authenticated_entry(
        catalog, _configured_ids(current_user.get("org_id"))
    )


@router.get("/llm/setting/{provider}")
async def llm_settings(
    provider: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        catalog = provider_settings(Kind.LLM, provider)
    except Exception as exc:
        _catalog_http_error(exc)
        raise
    return _with_authenticated_entry(
        catalog, _configured_ids(current_user.get("org_id"))
    )


@router.get("/telephony/setting/{provider}")
async def telephony_settings(
    provider: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        catalog = telephony_provider_settings(provider)
    except Exception as exc:
        _catalog_http_error(exc)
        raise
    return _with_authenticated_entry(
        catalog, _configured_ids(current_user.get("org_id"))
    )
