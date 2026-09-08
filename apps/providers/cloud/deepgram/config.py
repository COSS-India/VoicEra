"""Deepgram provider configuration (STT + TTS)."""

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
    DEFAULT_TTS_VOICE,
)

_STT_MODELS = model_ids(STT_CAPABILITIES)
_TTS_MODELS = model_ids(TTS_CAPABILITIES)


class DeepgramAuth(BaseModel):
    api_key: str | list[str] = Field(
        description="Deepgram API key (or a list for rotation).",
        json_schema_extra={"secret": True},
    )


class DeepgramSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class DeepgramTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description="Deepgram Aura voice ID (aura-2-… or aura-… for Aura-1).",
        json_schema_extra={
            "examples": list(TTS_VOICES),
            "allow_custom_input": True,
        },
    )


class DeepgramSTTConfig(DeepgramAuth, DeepgramSTTSettings, BaseSTTConfig):
    """Deepgram speech-to-text configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Deepgram"

    provider: Literal["deepgram"] = "deepgram"
    model: str = Field(
        default=_STT_MODELS[0],
        description="Deepgram STT model.",
        json_schema_extra={
            "examples": list(_STT_MODELS),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="multi",
        description=(
            "Canonical language id, or 'multi' for auto-detection. "
            "flux-general-en only accepts 'en'."
        ),
        json_schema_extra=language_schema_extra(
            languages_map(STT_CAPABILITIES),
        ),
    )


class DeepgramTTSConfig(DeepgramAuth, DeepgramTTSSettings, BaseTTSConfig):
    """Deepgram Aura text-to-speech configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Deepgram"

    provider: Literal["deepgram"] = "deepgram"
    model: str = Field(
        default=_TTS_MODELS[0],
        description=(
            "Deepgram TTS model family. The voice ID is what Pipecat sends "
            "as the Deepgram model (aura-2-… vs aura-…)."
        ),
        json_schema_extra={
            "examples": list(_TTS_MODELS),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="en",
        description="Language code. Deepgram TTS is currently English-only.",
        json_schema_extra=language_schema_extra(
            languages_map(TTS_CAPABILITIES),
            allow_custom_input=False,
        ),
    )
