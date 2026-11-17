"""Go To Market telephony provider configuration (auth + settings)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from apps.telephony.base import BaseTelephonyAuth, BaseTelephonyConfig, BaseTelephonySettings
from apps.telephony.registry import register_telephony

from .auth_helpers import parse_obd_profiles, serialize_obd_profiles

DEFAULT_GO2MARKET_OBD_BASE_URL = (
    "https://obd.voicensms.in/obd/OBDAPI/webresources"
)

_OBD_PAIR_FIELDS = [
    {
        "key": "serviceno",
        "label": "Service Number",
        "placeholder": "7971504853",
        "description": "Go To Market service number (10-digit).",
        "normalize": "digits",
    },
    {
        "key": "ukey",
        "label": "UKey",
        "placeholder": "hPg8byNlNi2whG1lfv8SdErwYem_vQZ-KA==",
        "description": "User authentication key from your Go To Market profile.",
    },
    {
        "key": "ivrtemplateid",
        "label": "IVR Template ID",
        "placeholder": "193",
        "description": "IVR template id configured in the Go To Market portal.",
    },
]


class Go2MarketAuth(BaseTelephonyAuth):
    """Auth is stored as ``obd_profiles`` rows; legacy fields are derived for dialing."""

    auth_id: str = Field(
        default="",
        description="Derived serviceno from the first OBD profile (internal).",
        json_schema_extra={"integration_model": "Go2MarketServiceNo"},
    )
    auth_token: str = Field(
        default="",
        description="Derived ukey from the first OBD profile (internal).",
        json_schema_extra={
            "integration_model": "Go2MarketUkey",
        },
    )
    ivrtemplateid: str = Field(
        default="",
        description="Derived IVR template from the first OBD profile (internal).",
        json_schema_extra={"integration_model": "Go2MarketIvrTemplateId"},
    )
    obd_profiles: str = Field(
        description=(
            "One or more Go To Market outbound profiles (service number, UKey, IVR template)."
        ),
        json_schema_extra={
            "secret": True,
            "integration_model": "Go2MarketObdProfiles",
            "ui_label": "Go To Market profile",
            "pair_fields": _OBD_PAIR_FIELDS,
            "examples": [
                '[{"serviceno":"7971504853","ukey":"YOUR_UKEY","ivrtemplateid":"193"}]'
            ],
        },
    )

    @field_validator("obd_profiles", mode="before")
    @classmethod
    def _normalize_obd_profiles(cls, value: object) -> str:
        if isinstance(value, list):
            return serialize_obd_profiles(value)  # type: ignore[arg-type]
        return str(value or "")

    @model_validator(mode="after")
    def _sync_primary_profile(self) -> "Go2MarketAuth":
        pairs = parse_obd_profiles(self.obd_profiles)
        primary = pairs[0]
        object.__setattr__(self, "auth_id", primary["serviceno"])
        object.__setattr__(self, "auth_token", primary["ukey"])
        object.__setattr__(self, "ivrtemplateid", primary["ivrtemplateid"])
        return self


class Go2MarketSettings(BaseTelephonySettings):
    base_url: str = Field(
        default=DEFAULT_GO2MARKET_OBD_BASE_URL,
        description="Go To Market OBD API base URL (CreateOBDCampaignPost appended).",
        json_schema_extra={
            "examples": [DEFAULT_GO2MARKET_OBD_BASE_URL],
            "allow_custom_input": True,
        },
    )
    campaigntype: str = Field(
        default="4",
        description="OBD campaign type (4 = transactional).",
    )
    retryatmpt: str = Field(default="0", description="Retry attempts on failure.")
    retryduration: str = Field(default="15", description="Retry duration (minutes).")


@register_telephony
class Go2MarketConfig(Go2MarketAuth, Go2MarketSettings, BaseTelephonyConfig):
    """Go To Market OBD outbound + bi-directional audio streaming."""

    name: str = "Go To Market"
    provider: Literal["go2market"] = "go2market"
