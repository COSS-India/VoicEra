"""Indic Parler TTS configuration."""

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


class IndicParlerTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description=(
            "Parler speaker name, prepended to the style description. Optional: "
            "empty means the description alone sets the voice."
        ),
    )
    style: str = Field(
        default=DEFAULT_TTS_STYLE,
        description=(
            "Free-text voice description sent as OpenAI instructions (pitch, pace, "
            "tone, recording quality). The examples are a starting point."
        ),
        json_schema_extra={"examples": list(TTS_STYLES)},
    )


class IndicParlerTTSConfig(IndicParlerTTSSettings, BaseTTSConfig):
    """Self-hosted AI4Bharat Indic Parler via the model-server OpenAI speech API."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Indic Parler"

    provider: Literal["indic_parler"] = "indic_parler"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Parler model id as reported by GET /v1/models.",
        json_schema_extra={"examples": list(_TTS_MODELS)},
    )
    language: str = Field(
        default="hi",
        description=(
            "Canonical language id. Selects the speaker roster; on the wire the "
            "text's script carries the language."
        ),
        json_schema_extra=language_schema_extra(languages_map(TTS_CAPABILITIES)),
    )
