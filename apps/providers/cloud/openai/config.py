"""OpenAI LLM + STT + TTS configuration."""

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
    TTS_VOICES,
    DEFAULT_LLM_MODEL,
    DEFAULT_TTS_VOICE,
)

_STT_MODELS = model_ids(STT_CAPABILITIES)
_TTS_MODELS = model_ids(TTS_CAPABILITIES)


class OpenAIAuth(BaseModel):
    api_key: str | list[str] = Field(
        description="OpenAI API key (or a list for rotation).",
        json_schema_extra={"secret": True},
    )


class OpenAILLMSettings(BaseLLMSettings):
    """Standard LLM sampling knobs. API host is Pipecat's OpenAI default."""


class OpenAISTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class OpenAITTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description="OpenAI TTS voice name.",
        json_schema_extra={"examples": list(TTS_VOICES)},
    )


class OpenAILLMConfig(OpenAIAuth, OpenAILLMSettings, BaseLLMConfig):
    """OpenAI chat LLM configuration."""

    name: str = "OpenAI"

    provider: Literal["openai"] = "openai"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description="OpenAI chat model.",
        json_schema_extra={
            "examples": list(LLM_MODELS),
            "allow_custom_input": True,
        },
    )


class OpenAISTTConfig(OpenAIAuth, OpenAISTTSettings, BaseSTTConfig):
    """OpenAI transcription configuration (gpt-4o-transcribe)."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "OpenAI"

    provider: Literal["openai"] = "openai"
    model: str = Field(
        default=_STT_MODELS[0],
        description="OpenAI transcription model.",
        json_schema_extra={"examples": list(_STT_MODELS)},
    )
    language: str = Field(
        default="en",
        description="ISO 639-1 language code for transcription.",
        json_schema_extra=language_schema_extra(languages_map(STT_CAPABILITIES)),
    )


class OpenAITTSConfig(OpenAIAuth, OpenAITTSSettings, BaseTTSConfig):
    """OpenAI TTS configuration (gpt-4o-mini-tts)."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "OpenAI"

    provider: Literal["openai"] = "openai"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="OpenAI TTS model.",
        json_schema_extra={"examples": list(_TTS_MODELS)},
    )
    language: str = Field(
        default="en",
        description="ISO 639-1 language code for synthesis.",
        json_schema_extra=language_schema_extra(languages_map(TTS_CAPABILITIES)),
    )
