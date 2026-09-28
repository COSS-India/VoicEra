"""Raya (Bakbak) STT + TTS configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseSTTConfig, BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import (
    DEFAULT_BASE_URL,
    DEFAULT_TTS_SAMPLE_RATE,
    DEFAULT_TTS_VOICE,
    STT_CAPABILITIES,
    TTS_CAPABILITIES,
)

_STT_MODELS = model_ids(STT_CAPABILITIES)
_TTS_MODELS = model_ids(TTS_CAPABILITIES)


class RayaAuth(BaseModel):
    api_key: str = Field(
        description="Raya API key (env: RAYA_API_KEY).",
        json_schema_extra={"secret": True},
    )


class RayaSTTSettings(BaseModel):
    """No STT knobs beyond model and language (WS URL is hardcoded in catalog)."""


class RayaTTSSettings(BaseTTSSettings):
    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description="Raya voice name (mapped to voice_id when calling the API).",
        json_schema_extra={"allow_custom_input": True},
    )
    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=1.5,
        description="Speech speed multiplier (0.5 to 1.5).",
    )
    sample_rate: int = Field(
        default=DEFAULT_TTS_SAMPLE_RATE,
        description="Audio sample rate in Hz.",
        json_schema_extra={"examples": [8000, 16000, 22050, 24000]},
    )
    base_url: str | None = Field(
        default=None,
        description=f"Override the TTS HTTP base URL (default: {DEFAULT_BASE_URL}).",
    )


class RayaSTTConfig(RayaAuth, RayaSTTSettings, BaseSTTConfig):
    """Raya Bakbak STT configuration (WebSocket utterance transcription)."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Raya"

    provider: Literal["raya"] = "raya"
    model: str = Field(
        default=_STT_MODELS[0],
        description="Raya STT model.",
        json_schema_extra={
            "examples": list(_STT_MODELS),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="hi",
        description="Canonical language id (mapped to Raya STT wire codes).",
        json_schema_extra=language_schema_extra(
            languages_map(STT_CAPABILITIES),
        ),
    )


class RayaTTSConfig(RayaAuth, RayaTTSSettings, BaseTTSConfig):
    """Raya Bakbak TTS configuration (SSE streaming)."""

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Raya"

    provider: Literal["raya"] = "raya"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Raya TTS model. Voice IDs are model-specific (standard vs m1).",
        json_schema_extra={"examples": list(_TTS_MODELS)},
    )
    language: str = Field(
        default="hi",
        description="Canonical language id (mapped to Raya TTS wire codes).",
        json_schema_extra=language_schema_extra(
            languages_map(TTS_CAPABILITIES),
        ),
    )
