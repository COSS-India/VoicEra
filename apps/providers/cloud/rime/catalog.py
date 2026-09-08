"""Rime TTS model catalog."""

from ...capabilities import expand_settings

DEFAULT_TTS_VOICE = "celeste"

_TTS_LANGS = {
    "en": "en",
    "hi": "hi",
}

_SETTINGS = {
    "voice": {
        "default": DEFAULT_TTS_VOICE,
        "input_type": "input",
        "allow_custom_input": True,
    },
    "speed": {
        "default": 1.0,
        "minimum": 0.5,
        "maximum": 2.0,
        "input_type": "slider",
    },
}

TTS_CAPABILITIES = {
    model: {
        "languages": dict(_TTS_LANGS),
        "settings": expand_settings(_TTS_LANGS, _SETTINGS),
    }
    for model in ("arcana", "mistv3", "mistv2", "mist")
}
