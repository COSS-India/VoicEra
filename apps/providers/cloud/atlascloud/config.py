"""Atlas Cloud LLM configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...base import BaseLLMConfig, BaseLLMSettings
from .catalog import LLM_MODELS, DEFAULT_LLM_MODEL


class AtlasCloudAuth(BaseModel):
    api_key: str | list[str] = Field(
        description="Atlas Cloud API key.",
        json_schema_extra={"secret": True},
    )


class AtlasCloudLLMSettings(BaseLLMSettings):
    """Standard LLM sampling knobs. API host is the catalog default."""


class AtlasCloudLLMConfig(AtlasCloudAuth, AtlasCloudLLMSettings, BaseLLMConfig):
    """Atlas Cloud OpenAI-compatible LLM configuration."""

    name: str = "Atlas Cloud"

    provider: Literal["atlascloud"] = "atlascloud"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description="Atlas Cloud OpenAI-compatible chat model identifier.",
        json_schema_extra={
            "examples": list(LLM_MODELS),
            "allow_custom_input": True,
        },
    )
