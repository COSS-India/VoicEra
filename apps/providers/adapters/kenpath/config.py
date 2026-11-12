"""Kenpath Vistaar / Bharat Vistaar LLM configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

from ...base import BaseLLMConfig, BaseLLMSettings
from .catalog import (
    ALL_KENPATH_LANGUAGES,
    BHARAT_VISTAAR_DEV_AUTH_SECRET,
    BHARAT_VISTAAR_PROD_AUTH_SECRET,
    DEFAULT_LLM_MODEL,
    LLM_MODELS,
    VISTAAR_AUTH_SECRET,
)


class KenpathAuth(BaseModel):
    """Three PEMs matching mono kenpath_llm keys.

    - ``private_key`` → ``jwt_private_key.pem`` (Vistaar ``/api/voice/``)
    - ``bharat_prod_private_key`` → ``prod_private_key_bh.pem`` (Bharat prod)
    - ``bharat_dev_private_key`` → ``dev_private_key_bh.pem`` (Bharat dev)
    """

    private_key: str = Field(
        default="",
        description=(
            "RSA PEM for Vistaar JWTs (iss=voice era). "
            f"Mono: jwt_private_key.pem. Catalog auth secret: {VISTAAR_AUTH_SECRET}."
        ),
        json_schema_extra={"multiline": True, "secret": True},
    )
    bharat_prod_private_key: str = Field(
        default="",
        description=(
            "RSA PEM for Bharat Vistaar prod JWTs (iss=samvaad). "
            f"Mono: prod_private_key_bh.pem. Catalog auth secret: {BHARAT_VISTAAR_PROD_AUTH_SECRET}."
        ),
        json_schema_extra={"multiline": True, "secret": True},
    )
    bharat_dev_private_key: str = Field(
        default="",
        description=(
            "RSA PEM for Bharat Vistaar dev JWTs (iss=samvaad). "
            f"Mono: dev_private_key_bh.pem. Catalog auth secret: {BHARAT_VISTAAR_DEV_AUTH_SECRET}."
        ),
        json_schema_extra={"multiline": True, "secret": True},
    )


class KenpathLLMSettings(BaseLLMSettings):
    jwt_sub: str = Field(
        default="+91-9036722772",
        description=(
            "Fallback JWT sub for Vistaar /api/voice/ when the call participant phone "
            "is unavailable (ignored for Bharat Vistaar)."
        ),
    )
    send_phone_number_to_llm: bool = Field(
        default=False,
        validation_alias=AliasChoices("send_phone_number_to_llm", "use_participant_phone"),
        description=(
            "When enabled, send the telephony caller/callee number to the LLM "
            "(Kenpath Vistaar JWT sub when available)."
        ),
        json_schema_extra={
            "label": "Send phone number to LLM",
            "input_type": "switch",
            "examples": [False, True],
        },
    )
    send_greeting_to_llm: bool = Field(
        default=False,
        description=(
            "When enabled, record the spoken greeting in LLM context on connect and "
            "send it as advisory_text on the first GET /api/voice/ request per call."
        ),
        json_schema_extra={"examples": [False, True]},
    )
    base_url: str | None = Field(
        default=None,
        description="Override the catalog base URL for the selected model.",
    )


class KenpathLLMConfig(KenpathAuth, KenpathLLMSettings, BaseLLMConfig):
    """Kenpath Vistaar / Bharat Vistaar LLM configuration."""

    name: str = "Kenpath"

    provider: Literal["kenpath"] = "kenpath"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description="Vistaar or Bharat Vistaar environment (prod or dev).",
        json_schema_extra={"examples": list(LLM_MODELS)},
    )
    source_lang: str = Field(
        default="mr",
        description=(
            "Language code for the selected model "
            "(Vistaar: mr/bhb; Bharat Vistaar: X-Language, e.g. en/hi)."
        ),
        json_schema_extra={"examples": list(ALL_KENPATH_LANGUAGES)},
    )
    target_lang: str = Field(
        default="mr",
        description="Vistaar target_lang (ignored for Bharat Vistaar).",
        json_schema_extra={"examples": list(ALL_KENPATH_LANGUAGES)},
    )
