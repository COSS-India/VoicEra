"""Bhashini STT and TTS configuration."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ...base import BaseSTTConfig, BaseTTSConfig, BaseTTSSettings
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import (
    DEFAULT_ORPHEUS_STYLE,
    DEFAULT_ORPHEUS_VOICE,
    DEFAULT_TTS_DESCRIPTION,
    DEFAULT_TTS_VOICE,
    ORPHEUS_STYLES,
    STT_CAPABILITIES,
    TTS_CAPABILITIES,
)

_STT_MODELS = model_ids(STT_CAPABILITIES)
_TTS_MODELS = model_ids(TTS_CAPABILITIES)


class BhashiniSTTAuth(BaseModel):
    api_key: str = Field(
        description=(
            "Dhruva API key (BHASHINI_API_KEY). Used by WebSocket and Socket.IO STT."
        ),
        json_schema_extra={"secret": True},
    )
    bhili_auth_token: str = Field(
        default="",
        description=(
            "NVCF Bearer token for Bhili STT gRPC "
            "(BHASHINI_BHILI_STT_AUTH_TOKEN). Separate from TTS auth_token."
        ),
        json_schema_extra={"secret": True},
    )
    bhili_function_id: str = Field(
        default="",
        description=(
            "NVCF function id for Bhili STT gRPC "
            "(BHASHINI_BHILI_STT_FUNCTION_ID). Separate from TTS function_id."
        ),
        json_schema_extra={"secret": True},
    )
    nemotron_auth_token: str = Field(
        default="",
        description=(
            "NVCF Bearer token for Nemotron Indic STT gRPC "
            "(BHASHINI_NEMOTRON_STT_AUTH_TOKEN). Separate from Bhili / TTS tokens."
        ),
        json_schema_extra={"secret": True},
    )
    nemotron_function_id: str = Field(
        default="",
        description=(
            "NVCF function id for Nemotron Indic STT gRPC "
            "(BHASHINI_NEMOTRON_STT_FUNCTION_ID). Separate from Bhili / TTS function ids."
        ),
        json_schema_extra={"secret": True},
    )


class BhashiniSTTSettings(BaseModel):
    """No extra STT knobs beyond model and language."""


class BhashiniSTTConfig(BhashiniSTTAuth, BhashiniSTTSettings, BaseSTTConfig):
    """Bhashini STT configuration (WebSocket, Socket.IO, Bhili, or Nemotron NVCF)."""

    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    name: str = "Bhashini"

    provider: Literal["bhashini"] = "bhashini"
    model: str = Field(
        default=_STT_MODELS[0],
        description=(
            "Bhashini STT model (conformer WS, Whisper Socket.IO, Bhili, or Nemotron)."
        ),
        json_schema_extra={"examples": list(_STT_MODELS)},
    )
    language: str = Field(
        default="hi",
        description="Canonical language id for transcription.",
        json_schema_extra=language_schema_extra(languages_map(STT_CAPABILITIES)),
    )


class BhashiniTTSAuth(BaseModel):
    auth_token: str = Field(
        default="",
        description=(
            "NVCF Bearer token for Indic Parler TTS gRPC "
            "(BHASHINI_TTS_AUTH_TOKEN). Separate from Orpheus / Bhili tokens."
        ),
        json_schema_extra={"secret": True},
    )
    function_id: str = Field(
        default="",
        description=(
            "NVCF function id for Indic Parler TTS gRPC "
            "(BHASHINI_TTS_FUNCTION_ID). Separate from Orpheus / Bhili function ids."
        ),
        json_schema_extra={"secret": True},
    )
    orpheus_auth_token: str = Field(
        description=(
            "NVCF Bearer token for Orpheus Indic TTS HTTP "
            "(BHASHINI_ORPHEUS_TTS_AUTH_TOKEN)."
        ),
        json_schema_extra={"secret": True},
    )
    orpheus_function_id: str = Field(
        description=(
            "NVCF function id for Orpheus Indic TTS HTTP "
            "(BHASHINI_ORPHEUS_TTS_FUNCTION_ID)."
        ),
        json_schema_extra={"secret": True},
    )


class BhashiniParlerTTSSettings(BaseTTSSettings):
    """Indic Parler TTS knobs."""

    voice: str = Field(
        default=DEFAULT_TTS_VOICE,
        description="Speaker name prepended to the voice description.",
    )
    description: str = Field(
        default=DEFAULT_TTS_DESCRIPTION,
        description="Preset or custom voice description sent to Indic Parler TTS.",
    )


class BhashiniOrpheusTTSSettings(BaseTTSSettings):
    """Orpheus TTS knobs."""

    voice: str = Field(
        default=DEFAULT_ORPHEUS_VOICE,
        description="Speaker name; uniquely selects the language on Orpheus.",
    )
    style: str = Field(
        default=DEFAULT_ORPHEUS_STYLE,
        description="Speaking style from the Orpheus roster.",
        json_schema_extra={"examples": list(ORPHEUS_STYLES)},
    )


class BhashiniTTSConfig(
    BhashiniTTSAuth,
    BhashiniParlerTTSSettings,
    BhashiniOrpheusTTSSettings,
    BaseTTSConfig,
):
    """Bhashini TTS configuration (Indic Parler gRPC or Orpheus NVCF HTTP).

    Inherits Parler settings first so the shared ``voice`` field keeps the
    Parler default; Orpheus contributes ``style``.
    """

    settings_by_model_language: ClassVar[dict] = settings_tree(TTS_CAPABILITIES)

    name: str = "Bhashini"

    provider: Literal["bhashini"] = "bhashini"
    model: str = Field(
        default=_TTS_MODELS[0],
        description="Bhashini TTS model (Indic Parler or Orpheus).",
        json_schema_extra={"examples": list(_TTS_MODELS)},
    )
    language: str = Field(
        default="hi",
        description="Canonical language id for synthesis.",
        json_schema_extra=language_schema_extra(languages_map(TTS_CAPABILITIES)),
    )
