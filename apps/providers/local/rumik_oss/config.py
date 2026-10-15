"""Rumik OSS-1 TTS configuration."""

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


class RumikOssTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description=(
            "Rumik speaker name. Unlike Orpheus it does not select the language — "
            "all four voices cover all of them."
        ),
    )
    style: str = Field(
        default=DEFAULT_TTS_STYLE,
        description=(
            "Delivery description sent as OpenAI instructions: emotion, accent and "
            "pace, comma-separated. Free text — the examples are a starting point."
        ),
        json_schema_extra={"examples": list(TTS_STYLES)},
    )


class RumikOssTTSConfig(RumikOssTTSSettings, BaseTTSConfig):
    """Self-hosted Rumik OSS-1 via the model-server OpenAI speech API.

    Non-commercial licence (CC-BY-NC-4.0 with an acceptable-use addendum); see
    ``catalog.py`` and the model folder's README.
    """

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Rumik OSS"

    provider: Literal["rumik_oss"] = "rumik_oss"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Rumik model id as reported by GET /v1/models.",
        json_schema_extra={"examples": list(_TTS_MODELS)},
    )
    language: str = Field(
        default="hi",
        description="Canonical language id for synthesis (the script carries it on the wire).",
        json_schema_extra=language_schema_extra(languages_map(TTS_CAPABILITIES)),
    )
