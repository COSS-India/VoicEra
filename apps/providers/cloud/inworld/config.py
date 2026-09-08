"""Inworld AI TTS configuration."""

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


class InworldAuth(BaseModel):
    api_key: str = Field(
        description="Inworld AI API key.",
        json_schema_extra={"secret": True},
    )


class InworldTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description=(
            "Inworld voice ID. Use 'Ashley' for the default warm English voice, "
            "or a workspace voice ID for a cloned/custom voice."
        ),
        json_schema_extra={
            "examples": list(TTS_VOICES),
            "allow_custom_input": True,
        },
    )
    speed: float = Field(
        default=1.0,
        ge=0.25,
        le=4.0,
        description="Speech speed multiplier (0.25x – 4.0x).",
    )
    delivery_mode: Literal["STABLE", "BALANCED", "CREATIVE"] = Field(
        default="BALANCED",
        description=(
            "Controls stability vs. expressiveness for inworld-tts-2: "
            "STABLE, BALANCED, or CREATIVE."
        ),
    )


class InworldTTSConfig(InworldAuth, InworldTTSSettings, BaseTTSConfig):
    """Inworld AI streaming TTS configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Inworld"

    provider: Literal["inworld"] = "inworld"
    model: str = Field(
        default=model_ids(TTS_CAPABILITIES)[0],
        description="Inworld TTS model.",
        json_schema_extra={
            "examples": list(model_ids(TTS_CAPABILITIES)),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="en-US",
        description="BCP-47 language code for synthesis.",
        json_schema_extra=language_schema_extra(
            languages_map(TTS_CAPABILITIES),
        ),
    )
