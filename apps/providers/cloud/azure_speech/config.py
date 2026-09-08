"""Azure Speech Services STT + TTS configuration."""

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
    SPEECH_REGIONS,
)

_STT_MODELS = model_ids(STT_CAPABILITIES)
_TTS_MODELS = model_ids(TTS_CAPABILITIES)


class AzureSpeechAuth(BaseModel):
    api_key: str = Field(
        description="Azure Cognitive Services subscription key (Speech resource key).",
        json_schema_extra={"secret": True},
    )
    region: str = Field(
        default="eastus",
        description="Azure Speech service region (e.g. 'eastus').",
        json_schema_extra={"examples": list(SPEECH_REGIONS)},
    )


class AzureSpeechSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class AzureSpeechTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description="Azure Neural TTS voice name (e.g. 'en-US-AriaNeural').",
        json_schema_extra={
            "examples": list(TTS_VOICES),
            "allow_custom_input": True,
        },
    )
    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Speech speed multiplier (0.5 to 2.0).",
    )


class AzureSpeechSTTConfig(AzureSpeechAuth, AzureSpeechSTTSettings, BaseSTTConfig):
    """Azure Cognitive Services Speech-to-Text configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Azure Speech"

    provider: Literal["azure_speech"] = "azure_speech"
    model: str = Field(
        default=_STT_MODELS[0],
        description=(
            "Catalog label only — Pipecat Azure STT does not pass a recognition "
            "model name (uses the default Speech SDK recognizer)."
        ),
        json_schema_extra={
            "examples": list(_STT_MODELS),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="en-US",
        description="Canonical language id. Vendor codes are BCP-47 (e.g. 'hi-IN' → 'hi').",
        json_schema_extra=language_schema_extra(languages_map(STT_CAPABILITIES)),
    )


class AzureSpeechTTSConfig(AzureSpeechAuth, AzureSpeechTTSSettings, BaseTTSConfig):
    """Azure Neural TTS configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Azure Speech"

    provider: Literal["azure_speech"] = "azure_speech"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Azure TTS engine. Always 'neural' for Neural TTS.",
        json_schema_extra={"examples": list(_TTS_MODELS)},
    )
    language: str = Field(
        default="en-US",
        description="Canonical language id matching the voice locale.",
        json_schema_extra=language_schema_extra(languages_map(TTS_CAPABILITIES)),
    )
