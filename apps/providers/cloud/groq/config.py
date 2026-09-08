"""Groq LLM configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...base import BaseLLMConfig, BaseLLMSettings
from .catalog import LLM_MODELS, DEFAULT_LLM_MODEL


class GroqAuth(BaseModel):
    api_key: str | list[str] = Field(
        description="Groq API key (or a list for rotation).",
        json_schema_extra={"secret": True},
    )


class GroqLLMSettings(BaseLLMSettings):
    """Standard LLM sampling knobs."""


class GroqLLMConfig(GroqAuth, GroqLLMSettings, BaseLLMConfig):
    """Groq ultra-fast LLM inference configuration."""

    name: str = "Groq"

    provider: Literal["groq"] = "groq"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description="Groq-hosted model identifier.",
        json_schema_extra={
            "examples": list(LLM_MODELS),
            "allow_custom_input": True,
        },
    )
