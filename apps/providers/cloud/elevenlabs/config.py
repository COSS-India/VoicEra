"""ElevenLabs STT + TTS configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseSTTConfig, BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import (
    STT_CAPABILITIES,
    TTS_CAPABILITIES,
    TTS_SPEED_MIN,
    TTS_SPEED_MAX,
    DEFAULT_TTS_VOICE,
)


class ElevenLabsAuth(BaseModel):
    api_key: str = Field(
        description="ElevenLabs API key.",
        json_schema_extra={"secret": True},
    )


class ElevenLabsSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class ElevenLabsTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description=(
            "ElevenLabs voice ID from your Voice Library "
            "(e.g. '21m00Tcm4TlvDq8ikWAM')."
        ),
        json_schema_extra={"allow_custom_input": True},
    )
    speed: float = Field(
        default=1.0,
        ge=TTS_SPEED_MIN,
        le=TTS_SPEED_MAX,
        description=f"Speed of the voice ({TTS_SPEED_MIN} to {TTS_SPEED_MAX}).",
    )


class ElevenLabsSTTConfig(ElevenLabsAuth, ElevenLabsSTTSettings, BaseSTTConfig):
    """ElevenLabs Scribe STT configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "ElevenLabs"

    provider: Literal["elevenlabs"] = "elevenlabs"
    model: str = Field(
        default=model_ids(STT_CAPABILITIES)[0],
        description="ElevenLabs Scribe STT model.",
        json_schema_extra={
            "examples": list(model_ids(STT_CAPABILITIES)),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="en",
        description=(
            "Canonical language id. Use 'multi' for automatic language detection. "
            "Odia is vendor code 'or' (canonical 'od')."
        ),
        json_schema_extra=language_schema_extra(
            languages_map(STT_CAPABILITIES),
        ),
    )


class ElevenLabsTTSConfig(ElevenLabsAuth, ElevenLabsTTSSettings, BaseTTSConfig):
    """ElevenLabs TTS configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "ElevenLabs"

    provider: Literal["elevenlabs"] = "elevenlabs"
    model: str = Field(
        default=model_ids(TTS_CAPABILITIES)[0],
        description="ElevenLabs TTS model.",
        json_schema_extra={
            "examples": list(model_ids(TTS_CAPABILITIES)),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="en",
        description="ISO 639-1 language code for synthesis.",
        json_schema_extra=language_schema_extra(
            languages_map(TTS_CAPABILITIES),
        ),
    )
