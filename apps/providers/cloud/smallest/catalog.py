"""Smallest.ai model catalog (TTS Lightning + STT Pulse)."""

from ...capabilities import expand_settings

# --- STT ---
_PULSE_LANGUAGES = {
    "en": "en",
    "hi": "hi",
    "bn": "bn",
    "gu": "gu",
    "kn": "kn",
    "ml": "ml",
    "mr": "mr",
    "ta": "ta",
    "te": "te",
    "pa": "pa",
    "or": "od",
}

STT_CAPABILITIES = {
    "pulse": {
        "languages": _PULSE_LANGUAGES,
        "settings": expand_settings(_PULSE_LANGUAGES, {}),
    },
}

# --- TTS ---
DEFAULT_TTS_VOICE = "sophia"

# Standard voices — available on both models
TTS_VOICES: tuple[str, ...] = (
    "sophia", "avery", "liam", "lucas", "olivia",
    "ryan", "freya", "william",
    "devansh", "arjun", "niharika", "maya", "dhruv", "mia", "maithili",
)

# Premium voices — lightning_v3.1_pro only (American, British, Indian accents; en + hi)
TTS_PRO_VOICES: tuple[str, ...] = (
    "meher", "rhea", "aviraj",
    "cressida", "willow", "maverick",
)

TTS_SAMPLE_RATES: tuple[int, ...] = (8000, 16000, 24000)
DEFAULT_TTS_SAMPLE_RATE = 16000

_LIGHTNING_LANGUAGES = {
    "en": "en",
    "hi": "hi",
    "bn": "bn",
    "gu": "gu",
    "kn": "kn",
    "mr": "mr",
    "ta": "ta",
}

_LIGHTNING_PRO_LANGUAGES = {
    "en": "en",
    "hi": "hi",
}

_TTS_SPEED = {
    "default": 1.0,
    "minimum": 0.5,
    "maximum": 2.0,
    "input_type": "slider",
}

_TTS_SAMPLE_RATE = {
    "default": DEFAULT_TTS_SAMPLE_RATE,
    "options": list(TTS_SAMPLE_RATES),
    "input_type": "dropdown",
}

TTS_CAPABILITIES = {
    "lightning_v3.1": {
        "languages": _LIGHTNING_LANGUAGES,
        "settings": expand_settings(
            _LIGHTNING_LANGUAGES,
            {
                "voice": {
                    "default": DEFAULT_TTS_VOICE,
                    "options": list(TTS_VOICES),
                    "input_type": "both",
                    "allow_custom_input": True,
                },
                "speed": dict(_TTS_SPEED),
                "sample_rate": dict(_TTS_SAMPLE_RATE),
            },
        ),
    },
    "lightning_v3.1_pro": {
        "languages": _LIGHTNING_PRO_LANGUAGES,
        "settings": expand_settings(
            _LIGHTNING_PRO_LANGUAGES,
            {
                "voice": {
                    "default": DEFAULT_TTS_VOICE,
                    "options": list(TTS_VOICES + TTS_PRO_VOICES),
                    "input_type": "both",
                    "allow_custom_input": True,
                },
                "speed": dict(_TTS_SPEED),
                "sample_rate": dict(_TTS_SAMPLE_RATE),
            },
        ),
    },
}
