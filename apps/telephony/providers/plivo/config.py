"""Plivo telephony provider configuration (auth + settings)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from apps.telephony.base import BaseTelephonyAuth, BaseTelephonyConfig, BaseTelephonySettings
from apps.telephony.registry import register_telephony

DEFAULT_PLIVO_API_BASE_URL = "https://api.plivo.com/v1"


class PlivoAuth(BaseTelephonyAuth):
    auth_id: str = Field(
        description="Plivo Auth ID (Integrations model: PlivoAuthId).",
        json_schema_extra={
            "secret": True,
            "integration_model": "PlivoAuthId",
        },
    )
    auth_token: str = Field(
        description="Plivo Auth Token (Integrations model: PlivoAuthToken).",
        json_schema_extra={
            "secret": True,
            "integration_model": "PlivoAuthToken",
        },
    )


class PlivoSettings(BaseTelephonySettings):
    base_url: str = Field(
        default=DEFAULT_PLIVO_API_BASE_URL,
        description="Plivo REST API base URL.",
        json_schema_extra={
            "examples": [DEFAULT_PLIVO_API_BASE_URL],
            "allow_custom_input": True,
        },
    )


@register_telephony
class PlivoConfig(PlivoAuth, PlivoSettings, BaseTelephonyConfig):
    """Plivo cloud telephony."""

    name: str = "Plivo"
    provider: Literal["plivo"] = "plivo"
