"""ElevenLabs model catalog."""

from ...capabilities import expand_settings

# --- STT (Scribe) ---
_SCRIBE_LANGUAGES = {
    "auto": "multi",
    "as": "as",
    "bn": "bn",
    "en": "en",
    "gu": "gu",
    "hi": "hi",
    "kn": "kn",
    "ml": "ml",
    "mr": "mr",
    "ne": "ne",
    "or": "od",
    "pa": "pa",
    "sd": "sd",
    "ta": "ta",
    "te": "te",
    "ur": "ur",
}

STT_CAPABILITIES = {
    "scribe_v2_realtime": {
        "languages": _SCRIBE_LANGUAGES,
        "settings": expand_settings(_SCRIBE_LANGUAGES, {}),
    },
}

# --- TTS ---
# Default listed model is eleven_flash_v2_5; others are valid custom inputs.
DEFAULT_TTS_VOICE = "21m00Tcm4TlvDq8ikWAM"
DEFAULT_BASE_URL = "https://api.elevenlabs.io"

# Pipecat ElevenLabsTTSSettings documents speed 0.7–1.2 for WebSocket TTS.
TTS_SPEED_MIN = 0.7
TTS_SPEED_MAX = 1.2

_TTS_LANGUAGES = {
    "en": "en",
    "hi": "hi",
}

_VOICE = {
    "default": DEFAULT_TTS_VOICE,
    "input_type": "input",
    "allow_custom_input": True,
    "description": "ElevenLabs voice ID from your Voice Library.",
}

_SPEED = {
    "default": 1.0,
    "minimum": TTS_SPEED_MIN,
    "maximum": TTS_SPEED_MAX,
    "input_type": "slider",
}

TTS_CAPABILITIES = {
    model: {
        "languages": _TTS_LANGUAGES,
        "settings": expand_settings(
            _TTS_LANGUAGES,
            {
                "voice": dict(_VOICE),
                "speed": dict(_SPEED),
            },
        ),
    }
    for model in (
        "eleven_flash_v2_5",
        "eleven_turbo_v2_5",
        "eleven_multilingual_v2",
        "eleven_turbo_v2",
    )
}
