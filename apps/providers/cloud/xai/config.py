"""xAI TTS configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import (
    DEFAULT_TTS_VOICE,
    TTS_CAPABILITIES,
    TTS_MODEL_INTERNAL,
    TTS_VOICES,
)


class XAIAuth(BaseModel):
    api_key: str | list[str] = Field(
        description="xAI API key.",
        json_schema_extra={"secret": True},
    )


class XAITTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description="xAI voice persona.",
        json_schema_extra={
            "examples": list(TTS_VOICES),
            "allow_custom_input": True,
        },
    )


class XAITTSConfig(XAIAuth, XAITTSSettings, BaseTTSConfig):
    """xAI TTS configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "xAI"

    provider: Literal["xai"] = "xai"
    model: str = Field(
        default=model_ids(TTS_CAPABILITIES)[0],
        description="xAI TTS model. Fixed to 'xai-tts'; voice selection determines output.",
        json_schema_extra={"examples": [TTS_MODEL_INTERNAL]},
    )
    language: str = Field(
        default="en",
        description=(
            "Canonical language id (e.g. 'en', 'hi') or 'multi' "
            "for automatic language detection."
        ),
        json_schema_extra=language_schema_extra(
            languages_map(TTS_CAPABILITIES),
        ),
    )
