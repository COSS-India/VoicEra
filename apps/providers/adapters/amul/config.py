"""Amul dev voice LLM configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...base import BaseLLMConfig
from .catalog import DEFAULT_LLM_MODEL, LLM_MODELS


class AmulAuth(BaseModel):
    """Static bearer token for ``Authorization: Bearer``."""

    bearer_token: str = Field(
        default="",
        description="Bearer token for the Amul voice API (Authorization header).",
        json_schema_extra={"multiline": True, "secret": True},
    )


class AmulLLMConfig(AmulAuth, BaseLLMConfig):
    """Amul dev voice LLM. Host, farmer id, and Gujarati are fixed in the adapter."""

    name: str = "Amul"

    provider: Literal["amul"] = "amul"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description="Amul voice model. Answers stream as plain text from GET /api/voice/.",
        json_schema_extra={"examples": list(LLM_MODELS)},
    )
