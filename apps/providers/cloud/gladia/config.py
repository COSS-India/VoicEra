"""Gladia STT configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseSTTConfig
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import STT_CAPABILITIES


class GladiaAuth(BaseModel):
    api_key: str = Field(
        description="Gladia API key.",
        json_schema_extra={"secret": True},
    )


class GladiaSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class GladiaSTTConfig(GladiaAuth, GladiaSTTSettings, BaseSTTConfig):
    """Gladia speech-to-text configuration (solaria-1)."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Gladia"

    provider: Literal["gladia"] = "gladia"
    model: str = Field(
        default=model_ids(STT_CAPABILITIES)[0],
        description="Gladia STT model.",
        json_schema_extra={
            "examples": list(model_ids(STT_CAPABILITIES)),
            "allow_custom_input": True,
        },
    )
    language: str = Field(
        default="en",
        description="ISO 639-1 language code for transcription.",
        json_schema_extra=language_schema_extra(
            languages_map(STT_CAPABILITIES),
        ),
    )
