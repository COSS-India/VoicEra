"""Vodafone Idea (VI) telephony provider configuration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.telephony.base import BaseTelephonyConfig, BaseTelephonySettings
from apps.telephony.providers.vi.obd.normalize import (
    normalize_e164,
    phone_lookup_keys,
)
from apps.telephony.registry import register_telephony

DEFAULT_VI_OBD_BASE_URL = (
    "https://cts.myvi.in:8443/Cpaas/api/v1/obdcampaignapi"
)


class ViNumberFlowEntry(BaseModel):
    """One VI phone number and its portal DIY flow id."""

    model_config = ConfigDict(extra="ignore")

    phone_number: str = Field(description="DNI / caller ID (E.164, e.g. +919876543210).")
    flow_id: str = Field(description="VI DIY flow id for OBD createCampaign.")

    @field_validator("phone_number", "flow_id")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @property
    def normalized_phone(self) -> str:
        return normalize_e164(self.phone_number) or self.phone_number.strip()


class ViAuth(BaseModel):
    """VI Integrations auth — OBD credentials and configured number flows."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    obd_username: str = Field(
        description="OBD Username",
        json_schema_extra={
            "secret": True,
            "integration_model": "ViObdUsername",
        },
    )
    obd_password: str = Field(
        description="OBD Password",
        json_schema_extra={
            "secret": True,
            "integration_model": "ViObdPassword",
        },
    )
    number_flows: list[ViNumberFlowEntry] = Field(
        description="Phone numbers and VI flow IDs configured for this organisation.",
        min_length=1,
    )

    @field_validator("obd_username", "obd_password")
    @classmethod
    def _strip_secrets(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _unique_phones(self) -> "ViAuth":
        seen: set[str] = set()
        for entry in self.number_flows:
            key = entry.normalized_phone
            if key in seen:
                raise ValueError(
                    f"duplicate phone number in number_flows: {entry.phone_number}"
                )
            seen.add(key)
        return self


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

    def list_inventory_phones(self) -> list[str]:
        """E.164 phones for Numbers attach inventory picker."""
        return [entry.normalized_phone for entry in self.number_flows]

    def resolve_dial_context(self, phone_number: str) -> dict[str, str]:
        """Match linked phone to a configured flow + DNI fallback."""
        keys = phone_lookup_keys(phone_number)
        if not keys:
            raise ValueError("phone_number is required")

        for entry in self.number_flows:
            entry_keys = phone_lookup_keys(entry.phone_number)
            if keys & entry_keys:
                return {
                    "flow_id": entry.flow_id,
                    "fallback_phone": entry.normalized_phone,
                    "phone_number": entry.normalized_phone,
                }

        raise ValueError(
            f"No VI flow_id configured for phone {phone_number!r}. "
            "Add this number under Integrations → Vodafone Idea."
        )

    @classmethod
    def auth_from_stored(cls, auth: dict[str, Any]) -> dict[str, Any]:
        """Build constructor kwargs from ProviderAuth blob."""
        flows_raw = auth.get("number_flows") or []
        number_flows = [
            ViNumberFlowEntry.model_validate(item)
            for item in flows_raw
            if isinstance(item, dict)
        ]
        return {
            "obd_username": str(auth.get("obd_username") or "").strip(),
            "obd_password": str(auth.get("obd_password") or "").strip(),
            "number_flows": number_flows,
        }
