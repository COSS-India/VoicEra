"""Google configuration (LLM via AI Studio; STT/TTS via Cloud)."""

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


class GoogleAIStudioAuth(BaseModel):
    """Authentication for Google AI Studio (Gemini LLM)."""

    api_key: str | list[str] = Field(
        description="Google AI Studio API key (or a list for rotation).",
        json_schema_extra={"secret": True},
    )


class GoogleCloudAuth(BaseModel):
    """Authentication for Google Cloud Speech / TTS."""

    credentials: str | None = Field(
        default=None,
        description=(
            "Paste the entire Google service-account JSON file. "
            "If omitted, falls back to Application Default Credentials (ADC)."
        ),
        json_schema_extra={"multiline": True, "secret": True},
    )
    project_id: str | None = Field(
        default=None,
        description="Google Cloud project ID.",
    )


class GoogleLLMSettings(BaseLLMSettings):
    """Standard LLM sampling knobs."""


class GoogleSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class GoogleTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description=(
            "Chirp 3 HD voice ID in the format '<locale>-Chirp3-HD-<name>'. "
            "Example: 'en-US-Chirp3-HD-Charon'."
        ),
        json_schema_extra={
            "examples": list(TTS_VOICES),
            "allow_custom_input": True,
        },
    )
    speed: float = Field(
        default=1.0,
        ge=0.25,
        le=2.0,
        description="Speech speed multiplier for Google streaming TTS.",
    )


class GoogleLLMConfig(GoogleAIStudioAuth, GoogleLLMSettings, BaseLLMConfig):
    """Google Gemini LLM via Google AI Studio."""

    name: str = "Google"

    provider: Literal["google"] = "google"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description="Google Gemini model identifier.",
        json_schema_extra={
            "examples": list(LLM_MODELS),
            "allow_custom_input": True,
        },
    )


class GoogleSTTConfig(GoogleCloudAuth, GoogleSTTSettings, BaseSTTConfig):
    """Google Cloud Speech-to-Text V2 configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Google"

    provider: Literal["google"] = "google"
    model: str = Field(
        default=_STT_MODELS[0],
        description="Google STT model.",
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


class GoogleTTSConfig(GoogleCloudAuth, GoogleTTSSettings, BaseTTSConfig):
    """Google Cloud Text-to-Speech Chirp 3 HD configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Google"

    provider: Literal["google"] = "google"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Google TTS model.",
        json_schema_extra={
            "examples": list(_TTS_MODELS),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="en-US",
        description="Canonical language id. Vendor codes are BCP-47 matching the voice locale.",
        json_schema_extra=language_schema_extra(languages_map(TTS_CAPABILITIES)),
    )
