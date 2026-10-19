"""Inworld TTS model catalog."""

from ...capabilities import expand_settings

TTS_VOICES: tuple[str, ...] = ("Ashley",)
DEFAULT_TTS_VOICE = "Ashley"

# Voice preview calls this directly (URL allowlist: never built from request data).
TTS_ENDPOINT = "https://api.inworld.ai/tts/v1/voice"

_TTS_LANGS = {
    "en-US": "en-US",
}

TTS_CAPABILITIES = {
    "inworld-tts-2": {
        "languages": dict(_TTS_LANGS),
        "settings": expand_settings(
            _TTS_LANGS,
            {
                "voice": {
                    "default": DEFAULT_TTS_VOICE,
                    "options": list(TTS_VOICES),
                    "input_type": "both",
                    "allow_custom_input": True,
                },
                "speed": {
                    "default": 1.0,
                    "minimum": 0.25,
                    "maximum": 4.0,
                    "input_type": "slider",
                },
                "delivery_mode": {
                    "default": "BALANCED",
                    "options": ["STABLE", "BALANCED", "CREATIVE"],
                    "input_type": "dropdown",
                },
            },
        ),
    },
}
