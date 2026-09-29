"""Kenpath Labs (Svara) provider configuration (TTS)."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import (
    DEFAULT_TTS_VOICE,
    TTS_CAPABILITIES,
    TTS_SPEED_MAX,
    TTS_SPEED_MIN,
)

_TTS_MODELS = model_ids(TTS_CAPABILITIES)


class KenpathLabsAuth(BaseModel):
    api_key: str = Field(
        description="Svara API key (from platform.kenpathlabs.com).",
        json_schema_extra={"secret": True},
    )


class KenpathLabsTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description="Svara voice id (e.g. 'sv_enhdbrj5' for Aanya).",
        json_schema_extra={
            "examples": [DEFAULT_TTS_VOICE],
            "allow_custom_input": True,
        },
    )
    speed: float = Field(
        default=1.0,
        ge=TTS_SPEED_MIN,
        le=TTS_SPEED_MAX,
        description=f"Speaking rate ({TTS_SPEED_MIN} to {TTS_SPEED_MAX}).",
    )
    base_url: str | None = Field(
        default=None,
        description="Override the Svara API base URL.",
    )


class KenpathLabsTTSConfig(KenpathLabsAuth, KenpathLabsTTSSettings, BaseTTSConfig):
    """Kenpath Labs Svara text-to-speech configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Kenpath Labs"

    provider: Literal["kenpathlabs"] = "kenpathlabs"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Svara TTS model.",
        json_schema_extra={
            "examples": list(_TTS_MODELS),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="multi",
        description=(
            "Canonical language id, or 'multi' for Svara's automatic "
            "language detection ('auto')."
        ),
        json_schema_extra=language_schema_extra(
            languages_map(TTS_CAPABILITIES),
        ),
    )
