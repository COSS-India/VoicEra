"""Indic Nemotron STT configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseSTTConfig
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import STT_CAPABILITIES

_STT_MODELS = model_ids(STT_CAPABILITIES)


class IndicNemotronSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class IndicNemotronSTTConfig(IndicNemotronSTTSettings, BaseSTTConfig):
    """Self-hosted Nemotron streaming ASR via model-server ``/v1/asr/ws``."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Indic Nemotron"

    provider: Literal["indic_nemotron"] = "indic_nemotron"
    model: str = Field(
        default=_STT_MODELS[0],
        description="Nemotron model id as reported by GET /v1/models.",
        json_schema_extra={"examples": list(_STT_MODELS)},
    )
    language: str = Field(
        default="hi",
        description="Canonical language id for transcription (required; no auto-detect).",
        json_schema_extra=language_schema_extra(languages_map(STT_CAPABILITIES)),
    )
