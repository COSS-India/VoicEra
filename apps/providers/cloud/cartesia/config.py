"""Cartesia STT + TTS configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseSTTConfig, BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import (
    STT_CAPABILITIES,
    TTS_CAPABILITIES,
    DEFAULT_TTS_VOICE,
)

_STT_MODELS = model_ids(STT_CAPABILITIES)
_TTS_MODELS = model_ids(TTS_CAPABILITIES)


class CartesiaAuth(BaseModel):
    api_key: str = Field(
        description="Cartesia API key.",
        json_schema_extra={"secret": True},
    )


class CartesiaSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class CartesiaTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description="Cartesia voice ID (UUID). Find voice IDs in the Cartesia Playground.",
        json_schema_extra={"allow_custom_input": True},
    )
    speed: float = Field(
        default=1.0,
        ge=0.6,
        le=1.5,
        description="Speed of the voice (0.6 to 1.5).",
    )
    volume: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Volume multiplier for generated speech (0.5 to 2.0).",
    )


class CartesiaSTTConfig(CartesiaAuth, CartesiaSTTSettings, BaseSTTConfig):
    """Cartesia Ink STT configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Cartesia"

    provider: Literal["cartesia"] = "cartesia"
    model: str = Field(
        default=_STT_MODELS[0],
        description=(
            "Cartesia STT model. 'ink-2' is English-only; "
            "'ink-whisper' supports 100+ languages."
        ),
        json_schema_extra={
            "examples": list(_STT_MODELS),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="en",
        description="ISO 639-1 language code.",
        json_schema_extra=language_schema_extra(
            languages_map(STT_CAPABILITIES),
        ),
    )


class CartesiaTTSConfig(CartesiaAuth, CartesiaTTSSettings, BaseTTSConfig):
    """Cartesia Sonic TTS configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Cartesia"

    provider: Literal["cartesia"] = "cartesia"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Cartesia Sonic TTS model.",
        json_schema_extra={"examples": list(_TTS_MODELS)},
    )
    language: str = Field(
        default="en",
        description="ISO 639-1 language code.",
        json_schema_extra=language_schema_extra(
            languages_map(TTS_CAPABILITIES),
        ),
    )
