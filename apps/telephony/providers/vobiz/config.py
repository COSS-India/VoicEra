"""Vobiz telephony provider configuration (auth + settings)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from apps.telephony.base import BaseTelephonyAuth, BaseTelephonyConfig, BaseTelephonySettings
from apps.telephony.registry import register_telephony

DEFAULT_VOBIZ_API_BASE_URL = "https://api.vobiz.ai/api/v1"


class VobizAuth(BaseTelephonyAuth):
    auth_id: str = Field(
        description="Vobiz Auth ID (Integrations model: VobizAuthId).",
        json_schema_extra={
            "secret": True,
            "integration_model": "VobizAuthId",
        },
    )
    auth_token: str = Field(
        description="Vobiz Auth Token (Integrations model: VobizAuthToken).",
        json_schema_extra={
            "secret": True,
            "integration_model": "VobizAuthToken",
        },
    )


class VobizSettings(BaseTelephonySettings):
    base_url: str = Field(
        default=DEFAULT_VOBIZ_API_BASE_URL,
        description="Vobiz REST API base URL.",
        json_schema_extra={
            "examples": [DEFAULT_VOBIZ_API_BASE_URL, "https://api.vobiz.in/v1"],
            "allow_custom_input": True,
        },
    )


@register_telephony
class VobizConfig(VobizAuth, VobizSettings, BaseTelephonyConfig):
    """Vobiz (Plivo-compatible) cloud telephony."""

    name: str = "Vobiz"
    provider: Literal["vobiz"] = "vobiz"
