"""Cartesia model catalog."""

from ...capabilities import expand_settings

# --- STT ---
# ink-whisper first so model_ids(...)[0] matches the prior Field default.
_INK_2 = {"en": "en"}

_INK_WHISPER = {
    "en": "en",
    "hi": "hi",
    "bn": "bn",
    "ta": "ta",
    "te": "te",
    "gu": "gu",
    "kn": "kn",
    "ml": "ml",
    "mr": "mr",
    "pa": "pa",
    "as": "as",
    "ur": "ur",
    "ne": "ne",
    "sa": "sa",
    "sd": "sd",
}

STT_CAPABILITIES: dict[str, dict] = {
    "ink-whisper": {
        "languages": _INK_WHISPER,
        "settings": expand_settings(_INK_WHISPER, {}),
    },
    "ink-2": {
        "languages": _INK_2,
        "settings": expand_settings(_INK_2, {}),
    },
}

# --- TTS ---
# Sonic 3 / 3.5: 42 languages. Intersection with canonical ids only.
# Docs: https://docs.cartesia.ai/build-with-cartesia/tts-models/latest
_SONIC = {
    "en": "en",
    "hi": "hi",
    "bn": "bn",
    "ta": "ta",
    "te": "te",
    "gu": "gu",
    "kn": "kn",
    "ml": "ml",
    "mr": "mr",
    "pa": "pa",
}

DEFAULT_TTS_VOICE = "3faa81ae-d3d8-4ab1-9e44-e50e46d33c30"

_TTS_SETTINGS = {
    "voice": {
        "default": DEFAULT_TTS_VOICE,
        "input_type": "input",
        "allow_custom_input": True,
        "description": "Cartesia voice ID (UUID).",
    },
    "speed": {
        "default": 1.0,
        "minimum": 0.6,
        "maximum": 1.5,
        "input_type": "slider",
    },
    "volume": {
        "default": 1.0,
        "minimum": 0.5,
        "maximum": 2.0,
        "input_type": "slider",
    },
}

TTS_CAPABILITIES: dict[str, dict] = {
    "sonic-3.5": {
        "languages": dict(_SONIC),
        "settings": expand_settings(_SONIC, _TTS_SETTINGS),
    },
    "sonic-3": {
        "languages": dict(_SONIC),
        "settings": expand_settings(_SONIC, _TTS_SETTINGS),
    },
}
