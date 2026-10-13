"""Portuguese Chatterbox TTS model catalog (model-server ``tts/pt-chatterbox``)."""

from __future__ import annotations

from ..indic_orpheus.catalog import resolve_base_url  # same env var, same route

SAMPLE_RATE = 24000

# Slot id from model-server GET /v1/models (not the inference model name).
GATEWAY_MODEL_ID = "pt-chatterbox"
TTS_MODEL = "pt-chatterbox"

# The checkpoint has one built-in voice (conds.pt).
DEFAULT_TTS_VOICE = "default"
TTS_VOICES: tuple[str, ...] = (DEFAULT_TTS_VOICE,)

# Vendor language code → VoicEra canonical id.
_TTS_LANGS: dict[str, str] = {"pt": "pt-BR"}

TTS_CAPABILITIES: dict[str, dict] = {
    TTS_MODEL: {
        "languages": dict(_TTS_LANGS),
        "settings": {
            "pt": {
                "voice": {
                    "default": DEFAULT_TTS_VOICE,
                    "options": list(TTS_VOICES),
                    "input_type": "dropdown",
                    "description": "The checkpoint's built-in Brazilian Portuguese voice.",
                },
            },
        },
    },
}

__all__ = [
    "DEFAULT_TTS_VOICE",
    "GATEWAY_MODEL_ID",
    "SAMPLE_RATE",
    "TTS_CAPABILITIES",
    "TTS_MODEL",
    "TTS_VOICES",
    "resolve_base_url",
]
