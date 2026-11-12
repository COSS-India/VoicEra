"""Hima-ASR STT configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseSTTConfig
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import STT_CAPABILITIES

_STT_MODELS = model_ids(STT_CAPABILITIES)


class HimaASRSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language.

    Script style for code-switched speech (native / mixed) is a server-wide
    setting, ``HIMA_STYLE`` in model-server/.env, not a per-agent one.
    """


class HimaASRSTTConfig(HimaASRSTTSettings, BaseSTTConfig):
    """Self-hosted Hima-ASR via model-server ``/v1/realtime``."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Hima ASR"

    provider: Literal["hima_asr"] = "hima_asr"
    model: str = Field(
        default=_STT_MODELS[0],
        description="Hima-ASR model id as reported by GET /v1/models.",
        json_schema_extra={"examples": list(_STT_MODELS)},
    )
    language: str = Field(
        default="hi",
        description="Canonical language id for transcription (required).",
        json_schema_extra=language_schema_extra(languages_map(STT_CAPABILITIES)),
    )
