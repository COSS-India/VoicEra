"""Kenpath DLS LLM configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...base import BaseLLMConfig, BaseLLMSettings
from .catalog import DEFAULT_LLM_MODEL, LLM_MODELS, VISTAAR_AUTH_SECRET


class KenpathDlsAuth(BaseModel):
    """Vistaar JWT signing key (same PEM as Kenpath ``/api/voice/``)."""

    private_key: str = Field(
        default="",
        description=(
            "RSA PEM for Vistaar JWTs (iss=voice-provider). "
            f"Mono: jwt_private_key.pem. Catalog auth secret: {VISTAAR_AUTH_SECRET}."
        ),
        json_schema_extra={"multiline": True, "secret": True},
    )


class KenpathDlsLLMSettings(BaseLLMSettings):
    jwt_sub: str = Field(
        default="+91-9036722772",
        description="JWT subject (phone) claim for Vistaar /api/voice-dls/.",
    )
    base_url: str | None = Field(
        default=None,
        description="Override the catalog base URL for the selected model.",
    )


class KenpathDlsLLMConfig(KenpathDlsAuth, KenpathDlsLLMSettings, BaseLLMConfig):
    """Kenpath Vistaar DLS voice LLM configuration."""

    name: str = "Kenpath DLS"

    provider: Literal["kenpath-dls"] = "kenpath-dls"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description="Vistaar DLS voice model (Marathi / Bhili via <lang:…> markers).",
        json_schema_extra={"examples": list(LLM_MODELS)},
    )
