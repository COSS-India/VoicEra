"""Camb.ai TTS model catalog."""

from ...capabilities import expand_settings

TTS_VOICES: tuple[str, ...] = ("147320",)
DEFAULT_TTS_VOICE = "147320"  # Camb.ai uses numeric voice IDs

_TTS_LANGS = {
    "en-us": "en-US",
    "en-gb": "en-GB",
    "hi-in": "hi",
}

_VOICE = {
    "default": DEFAULT_TTS_VOICE,
    "options": list(TTS_VOICES),
    "input_type": "both",
    "allow_custom_input": True,
}

TTS_CAPABILITIES = {
    "mars-flash": {
        "languages": dict(_TTS_LANGS),
        "settings": expand_settings(_TTS_LANGS, {"voice": dict(_VOICE)}),
    },
    "mars-pro": {
        "languages": dict(_TTS_LANGS),
        "settings": expand_settings(_TTS_LANGS, {"voice": dict(_VOICE)}),
    },
    "mars-instruct": {
        "languages": dict(_TTS_LANGS),
        "settings": expand_settings(
            _TTS_LANGS,
            {
                "voice": dict(_VOICE),
                "user_instructions": {
                    "default": None,
                    "input_type": "input",
                    "description": "Custom instructions for mars-instruct only.",
                },
            },
        ),
    },
}
