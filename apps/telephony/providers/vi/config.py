"""Vodafone Idea (VI) telephony provider configuration.

Credentials for OBD dialing come from process environment
(``VI_OBD_USERNAME`` / ``VI_OBD_PASSWORD``), not ProviderAuth.
Auth fields exist for catalog / config-schema symmetry only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from apps.telephony.base import BaseTelephonyAuth, BaseTelephonyConfig, BaseTelephonySettings
from apps.telephony.registry import register_telephony

DEFAULT_VI_OBD_BASE_URL = (
    "https://cts.myvi.in:8443/Cpaas/api/v1/obdcampaignapi"
)


class ViAuth(BaseTelephonyAuth):
    auth_id: str = Field(
        default="env",
        description=(
            "Unused placeholder — VI OBD uses VI_OBD_USERNAME from the server environment."
        ),
        json_schema_extra={"secret": True, "integration_model": "ViObdUsername"},
    )
    auth_token: str = Field(
        default="env",
        description=(
            "Unused placeholder — VI OBD uses VI_OBD_PASSWORD from the server environment."
        ),
        json_schema_extra={"secret": True, "integration_model": "ViObdPassword"},
    )


class ViSettings(BaseTelephonySettings):
    base_url: str = Field(
        default=DEFAULT_VI_OBD_BASE_URL,
        description="VI CPaaS OBD campaign API base URL.",
        json_schema_extra={
            "examples": [DEFAULT_VI_OBD_BASE_URL],
            "allow_custom_input": True,
        },
    )


@register_telephony
class ViConfig(ViAuth, ViSettings, BaseTelephonyConfig):
    """Vodafone Idea CPaaS (OBD dial + direct WSS media)."""

    name: str = "Vodafone Idea"
    provider: Literal["vi"] = "vi"
