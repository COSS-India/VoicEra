"""Vodafone Idea (VI) telephony provider configuration (auth + settings)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from apps.telephony.base import BaseTelephonyAuth, BaseTelephonyConfig, BaseTelephonySettings
from apps.telephony.registry import register_telephony

from .auth_helpers import serialize_dni_flows

DEFAULT_VI_OBD_BASE_URL = (
    "https://cts.myvi.in:8443/Cpaas/api/v1/obdcampaignapi"
)


class ViAuth(BaseTelephonyAuth):
    auth_id: str = Field(
        description="VI CPaaS OBD username (Integrations model: ViAuthId).",
        json_schema_extra={
            "secret": True,
            "integration_model": "ViAuthId",
        },
    )
    auth_token: str = Field(
        description="VI CPaaS OBD password (Integrations model: ViAuthToken).",
        json_schema_extra={
            "secret": True,
            "integration_model": "ViAuthToken",
        },
    )
    dni_flows: str = Field(
        description=(
            "One or more DNI + DIY flow_id pairs. Enter DNI as E.164 "
            "+91XXXXXXXXXX; outbound OBD uses getActiveDNIList wire form."
        ),
        json_schema_extra={
            "secret": True,
            "integration_model": "ViDniFlows",
            "ui_label": "DNI + Flow pairs",
            "pair_fields": [
                {
                    "key": "dni",
                    "label": "DNI",
                    "placeholder": "+919876543210",
                    "description": "Indian mobile with country code. Example: +919876543210",
                    "normalize": "e164",
                },
                {
                    "key": "flow_id",
                    "label": "Flow ID",
                    "placeholder": "68sXGL6Llic/7YdDGEtGBg==",
                    "description": "DIY Voice Streaming flow id for this DNI.",
                },
            ],
            "examples": [
                '[{"dni":"+919876543210","flow_id":"68sXGL6Llic/7YdDGEtGBg=="}]'
            ],
        },
    )

    @field_validator("dni_flows", mode="before")
    @classmethod
    def _normalize_dni_flows(cls, value: object) -> str:
        if isinstance(value, list):
            return serialize_dni_flows(value)  # type: ignore[arg-type]
        return str(value or "")


class ViSettings(BaseTelephonySettings):
    base_url: str = Field(
        default=DEFAULT_VI_OBD_BASE_URL,
        description="VI CPaaS OBD API base URL.",
        json_schema_extra={
            "examples": [DEFAULT_VI_OBD_BASE_URL],
            "allow_custom_input": True,
        },
    )


@register_telephony
class ViConfig(ViAuth, ViSettings, BaseTelephonyConfig):
    """Vodafone Idea CPaaS OBD + DIY Voice Streaming."""

    name: str = "Vodafone Idea"
    provider: Literal["vi"] = "vi"
