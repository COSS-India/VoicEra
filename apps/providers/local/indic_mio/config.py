"""Indic-Mio TTS configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field

from ...base import BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import DEFAULT_TTS_VOICE, TTS_CAPABILITIES, TTS_VOICES

_TTS_MODELS = model_ids(TTS_CAPABILITIES)


class IndicMioTTSSettings(BaseTTSSettings):
    """Voice only: Indic-Mio has no style or description input."""

    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description=(
            "Indic-Mio speaker embedding. Does not select the language; it sets "
            "the accent, which is the language the voice was recorded in."
        ),
        json_schema_extra={"examples": list(TTS_VOICES)},
    )


class IndicMioTTSConfig(IndicMioTTSSettings, BaseTTSConfig):
    """Self-hosted SPRINGLab Indic-Mio via the model-server OpenAI speech API.

    Not yet run on hardware; see ``catalog.py``.
    """

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Indic-Mio"

    provider: Literal["indic_mio"] = "indic_mio"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Indic-Mio model id as reported by GET /v1/models.",
        json_schema_extra={"examples": list(_TTS_MODELS)},
    )
    language: str = Field(
        default="hi",
        description=(
            "Canonical language id. Picks the default voice; on the wire the "
            "text's script carries the language."
        ),
        json_schema_extra=language_schema_extra(languages_map(TTS_CAPABILITIES)),
    )
