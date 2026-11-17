"""Kenpath Labs (Svara) model catalog (TTS)."""

from ...capabilities import expand_settings

DEFAULT_BASE_URL = "https://api.kenpathlabs.com"
DEFAULT_TTS_VOICE = "sv_enhdbrj5"  # Aanya

TTS_SPEED_MIN = 0.7
TTS_SPEED_MAX = 1.5

# Svara's `lang` request field is a free-form hint ("hi", "hin", "hindi",
# "hi-IN", "auto"). We map a curated set of vendor codes to VoicEra canonical
# ids; allow_custom_input covers the rest of the 80 languages Svara supports.
_TTS_LANGUAGES = {
    "auto": "multi",
    "hi": "hi",
    "en": "en",
    "bn": "bn",
    "ta": "ta",
    "te": "te",
    "gu": "gu",
    "kn": "kn",
    "ml": "ml",
    "mr": "mr",
    "pa": "pa",
    "or": "od",
    "as": "as",
    "ur": "ur",
    "ne": "ne",
}

_VOICE = {
    "default": DEFAULT_TTS_VOICE,
    "input_type": "both",
    "allow_custom_input": True,
    "description": "Svara voice id (sv_-prefixed) from GET /v1/voices.",
}

_SPEED = {
    "default": 1.0,
    "minimum": TTS_SPEED_MIN,
    "maximum": TTS_SPEED_MAX,
    "input_type": "slider",
}

TTS_CAPABILITIES: dict[str, dict] = {
    "svara-tts-turbo": {
        "languages": dict(_TTS_LANGUAGES),
        "settings": expand_settings(
            _TTS_LANGUAGES,
            {
                "voice": dict(_VOICE),
                "speed": dict(_SPEED),
            },
        ),
    },
}
