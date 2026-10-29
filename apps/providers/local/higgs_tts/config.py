"""Higgs TTS 3 configuration."""

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
    TTS_VOICES,
)

_TTS_MODELS = model_ids(TTS_CAPABILITIES)


class HiggsTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description=(
            "Higgs reference voice. Does not select the language; it sets timbre "
            "and accent, which is the language the voice was recorded in."
        ),
        json_schema_extra={"examples": list(TTS_VOICES)},
    )
    style: str = Field(
        default=DEFAULT_TTS_STYLE,
        description=(
            "Delivery, sent as OpenAI instructions: one of the model's fixed control "
            "tags (e.g. 'emotion:contentment'), or 'none'. Free text is refused."
        ),
        json_schema_extra={"examples": list(TTS_STYLES)},
    )


class HiggsTTSConfig(HiggsTTSSettings, BaseTTSConfig):
    """Self-hosted Boson AI Higgs TTS 3 via the model-server OpenAI speech API.

    Non-commercial licence; not yet run on hardware. See ``catalog.py``.
    """

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Higgs TTS"

    provider: Literal["higgs_tts"] = "higgs_tts"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Higgs model id as reported by GET /v1/models.",
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
