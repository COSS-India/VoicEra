"""Kenpath DLS LLM configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...base import BaseLLMConfig, BaseLLMSettings
from .catalog import DEFAULT_LLM_MODEL, DEFAULT_URL, LLM_MODELS


class KenpathDlsAuth(BaseModel):
    """DLS host identity — base URL only (no JWT / PEM)."""

    url: str = Field(
        default=DEFAULT_URL,
        description=(
            "Vistaar DLS base URL "
            "(e.g. https://vistaar-dev.mahapocra.gov.in). "
            "Requests go to {url}/api/voice-dls/."
        ),
        json_schema_extra={"secret": True},
    )


class KenpathDlsLLMSettings(BaseLLMSettings):
    """No extra knobs — language is chosen by the DLS service via markers."""


class KenpathDlsLLMConfig(KenpathDlsAuth, KenpathDlsLLMSettings, BaseLLMConfig):
    """Kenpath Vistaar DLS voice LLM configuration."""

    name: str = "Kenpath DLS"

    provider: Literal["kenpath-dls"] = "kenpath-dls"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description="Vistaar DLS voice model (Marathi / Bhili via <lang:…> markers).",
        json_schema_extra={"examples": list(LLM_MODELS)},
    )
