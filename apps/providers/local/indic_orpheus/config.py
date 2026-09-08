"""Indic Orpheus TTS configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field

from ...base import BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import (
    DEFAULT_TTS_STYLE,
    DEFAULT_TTS_VOICE,
    TTS_CAPABILITIES,
    TTS_STYLES,
)

_TTS_MODELS = model_ids(TTS_CAPABILITIES)


class IndicOrpheusTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description="Orpheus speaker name (determines language).",
    )
    style: str = Field(
        default=DEFAULT_TTS_STYLE,
        description="Speaking style from the Orpheus roster (sent as OpenAI instructions).",
        json_schema_extra={"examples": list(TTS_STYLES)},
    )


class IndicOrpheusTTSConfig(IndicOrpheusTTSSettings, BaseTTSConfig):
    """Self-hosted Orpheus Indic TTS via model-server OpenAI speech API."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Indic Orpheus"

    provider: Literal["indic_orpheus"] = "indic_orpheus"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Orpheus model id as reported by GET /v1/models.",
        json_schema_extra={"examples": list(_TTS_MODELS)},
    )
    language: str = Field(
        default="hi",
        description="Canonical language id for synthesis (speaker implies language on the wire).",
        json_schema_extra=language_schema_extra(languages_map(TTS_CAPABILITIES)),
    )
