"""Portuguese Whisper STT configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseSTTConfig
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import STT_CAPABILITIES

_STT_MODELS = model_ids(STT_CAPABILITIES)


class PtWhisperSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class PtWhisperSTTConfig(PtWhisperSTTSettings, BaseSTTConfig):
    """Self-hosted Portuguese Whisper via model-server ``/v1/asr/ws``."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Portuguese Whisper"

    provider: Literal["pt_whisper"] = "pt_whisper"
    model: str = Field(
        default=_STT_MODELS[0],
        description="Model id as reported by GET /v1/models.",
        json_schema_extra={"examples": list(_STT_MODELS)},
    )
    language: str = Field(
        default="pt-BR",
        description="Canonical language id for transcription (Brazilian Portuguese only).",
        json_schema_extra=language_schema_extra(languages_map(STT_CAPABILITIES)),
    )
