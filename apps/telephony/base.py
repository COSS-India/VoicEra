"""Shared types and HTTP helpers for telephony providers.

Credentials are always injected by the caller — this package never looks up
org Integrations or Mongo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
DOWNLOAD_TIMEOUT = 120.0
DEFAULT_POLL_ATTEMPTS = 10
DEFAULT_POLL_INTERVAL_SECS = 2.0


class Kind(str, Enum):
    """Telephony capability kind (mirrors apps.providers.Kind)."""

    TELEPHONY = "telephony"


@dataclass(frozen=True)
class Credentials:
    """Provider account credentials passed in by the caller."""

    auth_id: str
    auth_token: str


@dataclass
class ApiResult:
    """Uniform provider API result compatible with existing backend routers."""

    status: str
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"status": self.status, "message": self.message}
        out.update(self.data)
        return out


def success(message: str = "", **extra: Any) -> Dict[str, Any]:
    return ApiResult(status="success", message=message, data=dict(extra)).to_dict()


def fail(message: str, **extra: Any) -> Dict[str, Any]:
    return ApiResult(status="fail", message=message, data=dict(extra)).to_dict()


def require_credentials(
    auth_id: Optional[str],
    auth_token: Optional[str],
    *,
    provider_label: str,
) -> Optional[Credentials]:
    """Return Credentials or None if either value is missing/blank."""
    del provider_label  # reserved for call-site messaging
    aid = (auth_id or "").strip()
    token = (auth_token or "").strip()
    if not aid or not token:
        return None
    return Credentials(auth_id=aid, auth_token=token)


def missing_credentials_result(provider_label: str, **extra: Any) -> Dict[str, Any]:
    return fail(
        f"{provider_label} Auth ID and Auth Token must be provided.",
        **extra,
    )


async def request_json(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    auth: Optional[tuple[str, str]] = None,
    json: Any = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    provider_label: str = "Telephony",
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Perform an HTTP request expecting JSON.

    Returns ``(data, None)`` on success or ``(None, error_message)`` on failure.
    ``data`` may be ``{}`` when the response body is empty.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                auth=auth,
                json=json,
                params=params,
            )
            response.raise_for_status()
            if not response.content:
                return {}, None
            try:
                return response.json(), None
            except ValueError:
                return {}, None
    except httpx.HTTPStatusError as e:
        msg = f"{provider_label} API error: {e.response.text}"
        logger.error(msg)
        return None, msg
    except httpx.RequestError as e:
        msg = f"Failed to connect to {provider_label} API: {e}"
        logger.error(msg)
        return None, msg
    except Exception as e:
        msg = f"{provider_label} request error: {e}"
        logger.error(msg)
        return None, msg


async def request_bytes(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    auth: Optional[tuple[str, str]] = None,
    timeout: float = DOWNLOAD_TIMEOUT,
    provider_label: str = "Telephony",
) -> Optional[bytes]:
    """Download raw bytes (e.g. a recording file)."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers, auth=auth)
            response.raise_for_status()
            return response.content
    except Exception as e:
        logger.error("%s download failed from %s: %s", provider_label, url, e)
        return None


def extract_app_id(data: Dict[str, Any]) -> Optional[str]:
    return data.get("app_id") or data.get("id") or data.get("application_id")


def extract_recording_id(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    return (
        data.get("recording_id")
        or data.get("recording_uuid")
        or data.get("recordingId")
        or data.get("uuid")
    )


def extract_recording_url(metadata: Any) -> Optional[str]:
    if not isinstance(metadata, dict):
        return None
    return (
        metadata.get("recording_url")
        or metadata.get("recordingUrl")
        or metadata.get("url")
    )


# ---------------------------------------------------------------------------
# Config catalog bases (Auth / Settings / Config) — same layering as apps.providers
# ---------------------------------------------------------------------------


class BaseTelephonyAuth(BaseModel):
    """Provider account credentials. Subclass and mark secrets with json_schema_extra."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    auth_id: str = Field(description="Provider account / auth ID.")
    auth_token: str = Field(description="Provider auth token.")


class BaseTelephonySettings(BaseModel):
    """Non-secret provider knobs (API base URL, …)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    base_url: str = Field(description="Provider REST API base URL.")


class BaseTelephonyConfig(BaseModel):
    """Common fields shared by every telephony provider configuration."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    kind: Kind = Kind.TELEPHONY
    name: str = Field(description="Display name shown in the UI.")
    provider: str
