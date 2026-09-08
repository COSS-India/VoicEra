"""Camb.ai TTS configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import (
    DEFAULT_TTS_VOICE,
    TTS_CAPABILITIES,
    TTS_VOICES,
)


class CambAuth(BaseModel):
    api_key: str = Field(
        description="Camb.ai API key.",
        json_schema_extra={"secret": True},
    )


class CambTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description="Camb.ai voice ID (numeric string, e.g. '147320').",
        json_schema_extra={
            "examples": list(TTS_VOICES),
            "allow_custom_input": True,
        },
    )
    user_instructions: str | None = Field(
        default=None,
        description="Custom instructions for the mars-instruct model only.",
    )


class CambTTSConfig(CambAuth, CambTTSSettings, BaseTTSConfig):
    """Camb.ai Mars TTS configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Camb.ai"

    provider: Literal["camb"] = "camb"
    model: str = Field(
        default=model_ids(TTS_CAPABILITIES)[0],
        description="Camb.ai TTS model.",
        json_schema_extra={"examples": list(model_ids(TTS_CAPABILITIES))},
    )
    language: str = Field(
        default="en-US",
        description="Canonical language id. Vendor codes are lowercase (e.g. 'en-us' → 'en-US').",
        json_schema_extra=language_schema_extra(
            languages_map(TTS_CAPABILITIES),
        ),
    )
