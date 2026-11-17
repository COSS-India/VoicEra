"""Indic Transcribe STT configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseSTTConfig
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import STT_CAPABILITIES

_STT_MODELS = model_ids(STT_CAPABILITIES)


class IndicTranscribeSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class IndicTranscribeSTTConfig(IndicTranscribeSTTSettings, BaseSTTConfig):
    """Self-hosted Indic Transcribe (Canary 1.2B) via model-server ``/v1/realtime``."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Indic Transcribe"

    provider: Literal["indic_transcribe"] = "indic_transcribe"
    model: str = Field(
        default=_STT_MODELS[0],
        description="Indic Transcribe model id as reported by GET /v1/models.",
        json_schema_extra={"examples": list(_STT_MODELS)},
    )
    language: str = Field(
        default="hi",
        description="Canonical language id for transcription (required; no auto-detect).",
        json_schema_extra=language_schema_extra(languages_map(STT_CAPABILITIES)),
    )
