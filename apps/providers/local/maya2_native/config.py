"""Maya 2 Native TTS configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field

from ...base import BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import DEFAULT_TTS_VOICE, TTS_CAPABILITIES, TTS_VOICES

_TTS_MODELS = model_ids(TTS_CAPABILITIES)


class Maya2NativeTTSSettings(BaseTTSSettings):
    """Voice only: Maya 2 Native has no style or description input."""

    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description=(
            "Maya named voice. Does not select the language, but each voice was "
            "trained on its own set of languages; the per-language options list "
            "only those."
        ),
        json_schema_extra={"examples": list(TTS_VOICES)},
    )


class Maya2NativeTTSConfig(Maya2NativeTTSSettings, BaseTTSConfig):
    """Self-hosted Maya Research Maya 2 Native via the model-server OpenAI speech API.

    Not yet run on hardware; see ``catalog.py``.
    """

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Maya 2 Native"

    provider: Literal["maya2_native"] = "maya2_native"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Maya model id as reported by GET /v1/models.",
        json_schema_extra={"examples": list(_TTS_MODELS)},
    )
    language: str = Field(
        default="hi",
        description=(
            "Canonical language id. Sent to the server on every request: the "
            "script cannot tell Marathi from Hindi or Assamese from Bengali."
        ),
        json_schema_extra=language_schema_extra(languages_map(TTS_CAPABILITIES)),
    )
