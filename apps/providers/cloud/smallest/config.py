"""Smallest.ai STT + TTS configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseSTTConfig, BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import (
    STT_CAPABILITIES,
    TTS_CAPABILITIES,
    TTS_VOICES,
    TTS_PRO_VOICES,
    TTS_SAMPLE_RATES,
    DEFAULT_TTS_VOICE,
    DEFAULT_TTS_SAMPLE_RATE,
)


class SmallestAuth(BaseModel):
    api_key: str = Field(
        description="Smallest.ai API key.",
        json_schema_extra={"secret": True},
    )


class SmallestSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class SmallestTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description=(
            "Smallest.ai voice name. Pro voices (meher, rhea, etc.) "
            "require lightning_v3.1_pro."
        ),
        json_schema_extra={
            "examples": list(TTS_VOICES + TTS_PRO_VOICES),
            "allow_custom_input": True,
        },
    )
    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Speech speed multiplier (0.5 to 2.0).",
    )
    sample_rate: int = Field(
        default=DEFAULT_TTS_SAMPLE_RATE,
        description="Audio sample rate in Hz.",
        json_schema_extra={"examples": list(TTS_SAMPLE_RATES)},
    )


class SmallestSTTConfig(SmallestAuth, SmallestSTTSettings, BaseSTTConfig):
    """Smallest.ai Pulse STT configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Smallest.ai"

    provider: Literal["smallest"] = "smallest"
    model: str = Field(
        default=model_ids(STT_CAPABILITIES)[0],
        description="Smallest.ai STT model.",
        json_schema_extra={"examples": list(model_ids(STT_CAPABILITIES))},
    )
    language: str = Field(
        default="en",
        description="ISO 639-1 language code. Odia is vendor code 'or' (canonical 'od').",
        json_schema_extra=language_schema_extra(
            languages_map(STT_CAPABILITIES),
        ),
    )


class SmallestTTSConfig(SmallestAuth, SmallestTTSSettings, BaseTTSConfig):
    """Smallest.ai Lightning TTS configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Smallest.ai"

    provider: Literal["smallest"] = "smallest"
    model: str = Field(
        default=model_ids(TTS_CAPABILITIES)[0],
        description="Smallest.ai TTS model.",
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
