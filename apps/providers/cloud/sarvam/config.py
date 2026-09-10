"""Sarvam STT + TTS + LLM configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseLLMConfig, BaseLLMSettings, BaseSTTConfig, BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import (
    LLM_MODELS,
    STT_CAPABILITIES,
    TTS_CAPABILITIES,
    TTS_V3_VOICES,
    DEFAULT_LLM_MODEL,
    DEFAULT_TTS_V3_VOICE,
)


class SarvamAuth(BaseModel):
    api_key: str = Field(
        description="Sarvam API key.",
        json_schema_extra={"secret": True},
    )


class SarvamLLMSettings(BaseLLMSettings):
    temperature: float | None = Field(
        default=0.5,
        ge=0.0,
        le=2.0,
        description=(
            "Sampling temperature. Sarvam recommends 0.5 for balanced "
            "conversational responses."
        ),
    )


class SarvamSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class SarvamTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_V3_VOICE,
        description="Sarvam voice name. Available voices depend on the selected model.",
        json_schema_extra={
            "examples": list(TTS_V3_VOICES),
            "allow_custom_input": True,
        },
    )
    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Speech speed multiplier (0.5 to 2.0).",
    )


class SarvamLLMConfig(SarvamAuth, SarvamLLMSettings, BaseLLMConfig):
    """Sarvam LLM configuration."""

    name: str = "Sarvam"

    provider: Literal["sarvam"] = "sarvam"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description="Sarvam LLM model. Only models in the catalog are accepted.",
        json_schema_extra={
            "examples": list(LLM_MODELS),
            "allow_custom_input": False,
        },
    )


class SarvamSTTConfig(SarvamAuth, SarvamSTTSettings, BaseSTTConfig):
    """Sarvam Saarika/Saaras STT configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Sarvam"

    provider: Literal["sarvam"] = "sarvam"
    model: str = Field(
        default=model_ids(STT_CAPABILITIES)[0],
        description="Sarvam STT model.",
        json_schema_extra={
            "examples": list(model_ids(STT_CAPABILITIES)),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="multi",
        description=(
            "Canonical language id. Use 'multi' for auto-detection "
            "(saarika:v2.5+). Vendor codes are BCP-47 (e.g. 'hi-IN' → 'hi')."
        ),
        json_schema_extra=language_schema_extra(
            languages_map(STT_CAPABILITIES),
        ),
    )


class SarvamTTSConfig(SarvamAuth, SarvamTTSSettings, BaseTTSConfig):
    """Sarvam Bulbul TTS configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Sarvam"

    provider: Literal["sarvam"] = "sarvam"
    model: str = Field(
        default=model_ids(TTS_CAPABILITIES)[0],
        description="Sarvam TTS model.",
        json_schema_extra={
            "examples": list(model_ids(TTS_CAPABILITIES)),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="hi",
        description="Canonical language id for synthesis (vendor codes are *-IN).",
        json_schema_extra=language_schema_extra(
            languages_map(TTS_CAPABILITIES),
        ),
    )
