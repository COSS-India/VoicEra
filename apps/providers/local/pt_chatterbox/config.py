"""Portuguese Chatterbox TTS configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field

from ...base import BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import DEFAULT_TTS_VOICE, TTS_CAPABILITIES, TTS_VOICES

_TTS_MODELS = model_ids(TTS_CAPABILITIES)


class PtChatterboxTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description="Voice name. The checkpoint ships one: 'default'.",
        json_schema_extra={"examples": list(TTS_VOICES)},
    )


class PtChatterboxTTSConfig(PtChatterboxTTSSettings, BaseTTSConfig):
    """Self-hosted Portuguese Chatterbox via model-server OpenAI speech API."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Portuguese Chatterbox"

    provider: Literal["pt_chatterbox"] = "pt_chatterbox"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Model id as reported by GET /v1/models.",
        json_schema_extra={"examples": list(_TTS_MODELS)},
    )
    language: str = Field(
        default="pt-BR",
        description="Canonical language id for synthesis (Brazilian Portuguese only).",
        json_schema_extra=language_schema_extra(languages_map(TTS_CAPABILITIES)),
    )
