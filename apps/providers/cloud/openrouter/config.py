"""OpenRouter LLM configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...base import BaseLLMConfig, BaseLLMSettings
from .catalog import LLM_MODELS, DEFAULT_LLM_MODEL


class OpenRouterAuth(BaseModel):
    api_key: str | list[str] = Field(
        description="OpenRouter API key.",
        json_schema_extra={"secret": True},
    )


class OpenRouterLLMSettings(BaseLLMSettings):
    """Standard LLM sampling knobs. API host is Pipecat's OpenRouter default."""


class OpenRouterLLMConfig(OpenRouterAuth, OpenRouterLLMSettings, BaseLLMConfig):
    """OpenRouter unified LLM gateway configuration."""

    name: str = "OpenRouter"

    provider: Literal["openrouter"] = "openrouter"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description="OpenRouter model slug in 'vendor/model' format.",
        json_schema_extra={
            "examples": list(LLM_MODELS),
            "allow_custom_input": True,
        },
    )
