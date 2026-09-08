"""Rime TTS configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import DEFAULT_TTS_VOICE, TTS_CAPABILITIES


class RimeAuth(BaseModel):
    api_key: str = Field(
        description="Rime API key.",
        json_schema_extra={"secret": True},
    )


class RimeTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description="Rime voice ID.",
        json_schema_extra={"allow_custom_input": True},
    )
    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Speech speed multiplier (0.5x – 2.0x).",
    )


class RimeTTSConfig(RimeAuth, RimeTTSSettings, BaseTTSConfig):
    """Rime TTS configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Rime"

    provider: Literal["rime"] = "rime"
    model: str = Field(
        default=model_ids(TTS_CAPABILITIES)[0],
        description="Rime TTS model.",
        json_schema_extra={
            "examples": list(model_ids(TTS_CAPABILITIES)),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="en",
        description="ISO 639-1 language code.",
        json_schema_extra=language_schema_extra(
            languages_map(TTS_CAPABILITIES),
        ),
    )
