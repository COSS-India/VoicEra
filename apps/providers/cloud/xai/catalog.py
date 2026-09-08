"""xAI TTS catalog.

xAI TTS has no separate model selector — the voice fully specifies the output.
"""

from ...capabilities import expand_settings

TTS_VOICES: tuple[str, ...] = ("eve", "ara", "leo", "rex", "sal")

# xAI TTS internal model constant (not user-selectable beyond this single id)
TTS_MODEL_INTERNAL = "xai-tts"

DEFAULT_TTS_VOICE = "eve"

_TTS_LANGS = {
    "en": "en",
    "hi": "hi",
    "auto": "multi",
}

TTS_CAPABILITIES = {
    TTS_MODEL_INTERNAL: {
        "languages": dict(_TTS_LANGS),
        "settings": expand_settings(
            _TTS_LANGS,
            {
                "voice": {
                    "default": DEFAULT_TTS_VOICE,
                    "options": list(TTS_VOICES),
                    "input_type": "dropdown",
                },
            },
        ),
    },
}
