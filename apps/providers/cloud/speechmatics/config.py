"""Speechmatics STT configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseSTTConfig
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import STT_CAPABILITIES


class SpeechmaticsAuth(BaseModel):
    api_key: str = Field(
        description="Speechmatics API key.",
        json_schema_extra={"secret": True},
    )


class SpeechmaticsSTTSettings(BaseModel):
    """Operating point is `model` (`enhanced` / `standard`)."""


class SpeechmaticsSTTConfig(SpeechmaticsAuth, SpeechmaticsSTTSettings, BaseSTTConfig):
    """Speechmatics speech-to-text configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Speechmatics"

    provider: Literal["speechmatics"] = "speechmatics"
    model: str = Field(
        default=model_ids(STT_CAPABILITIES)[0],
        description="Speechmatics operating point: 'enhanced' or 'standard'.",
        json_schema_extra={
            "examples": list(model_ids(STT_CAPABILITIES)),
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
