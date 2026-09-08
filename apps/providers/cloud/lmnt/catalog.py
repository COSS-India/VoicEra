"""LMNT TTS model catalog."""

from ...capabilities import expand_settings

TTS_VOICES: tuple[str, ...] = ("lily", "daniel", "ava", "caleb", "leah", "zeke")
DEFAULT_TTS_VOICE = "lily"

_TTS_LANGS = {
    "en": "en",
    "hi": "hi",
}

_VOICE = {
    "default": DEFAULT_TTS_VOICE,
    "options": list(TTS_VOICES),
    "input_type": "both",
    "allow_custom_input": True,
}

TTS_CAPABILITIES = {
    "aurora": {
        "languages": dict(_TTS_LANGS),
        "settings": expand_settings(_TTS_LANGS, {"voice": dict(_VOICE)}),
    },
    "blizzard": {
        "languages": dict(_TTS_LANGS),
        "settings": expand_settings(_TTS_LANGS, {"voice": dict(_VOICE)}),
    },
}
