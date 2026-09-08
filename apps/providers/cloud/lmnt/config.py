"""LMNT TTS configuration."""

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


class LmntAuth(BaseModel):
    api_key: str = Field(
        description="LMNT API key.",
        json_schema_extra={"secret": True},
    )


class LmntTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description=(
            "LMNT voice ID. Use a stock voice name or a custom voice ID "
            "from your LMNT account."
        ),
        json_schema_extra={
            "examples": list(TTS_VOICES),
            "allow_custom_input": True,
        },
    )


class LmntTTSConfig(LmntAuth, LmntTTSSettings, BaseTTSConfig):
    """LMNT TTS configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "LMNT"

    provider: Literal["lmnt"] = "lmnt"
    model: str = Field(
        default=model_ids(TTS_CAPABILITIES)[0],
        description=(
            "LMNT TTS model. 'aurora' is general-purpose; 'blizzard' "
            "targets expressive conversational speech."
        ),
        json_schema_extra={"examples": list(model_ids(TTS_CAPABILITIES))},
    )
    language: str = Field(
        default="en",
        description="ISO 639-1 language code.",
        json_schema_extra=language_schema_extra(
            languages_map(TTS_CAPABILITIES),
        ),
    )
