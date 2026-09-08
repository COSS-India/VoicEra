"""AssemblyAI STT configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseSTTConfig
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import STT_CAPABILITIES


class AssemblyAIAuth(BaseModel):
    api_key: str = Field(
        description="AssemblyAI API key.",
        json_schema_extra={"secret": True},
    )


class AssemblyAISTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class AssemblyAISTTConfig(AssemblyAIAuth, AssemblyAISTTSettings, BaseSTTConfig):
    """AssemblyAI realtime speech-to-text configuration."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "AssemblyAI"

    provider: Literal["assemblyai"] = "assemblyai"
    model: str = Field(
        default=model_ids(STT_CAPABILITIES)[0],
        description="AssemblyAI realtime STT model.",
        json_schema_extra={"examples": list(model_ids(STT_CAPABILITIES))},
    )
    language: str = Field(
        default="en",
        description="ISO 639-1 language code. Only 'en' is in the canonical set.",
        json_schema_extra=language_schema_extra(
            languages_map(STT_CAPABILITIES),
        ),
    )
