"""Google model catalog (LLM via AI Studio; STT/TTS via Google Cloud)."""

from ...capabilities import expand_settings

# --- LLM ---
LLM_MODELS: tuple[str, ...] = (
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
)

DEFAULT_LLM_MODEL = "gemini-3.5-flash"

DEFAULT_STT_LOCATION = "global"

# Chirp 3 HD voice IDs follow the pattern <locale>-Chirp3-HD-<voice_name>
# Curated en-US set; other locales accept custom Chirp3-HD ids.
TTS_VOICES: tuple[str, ...] = (
    "en-US-Chirp3-HD-Charon",
    "en-US-Chirp3-HD-Puck",
    "en-US-Chirp3-HD-Kore",
    "en-US-Chirp3-HD-Fenrir",
    "en-US-Chirp3-HD-Aoede",
)

DEFAULT_TTS_VOICE = "en-US-Chirp3-HD-Charon"

_STT_LANGS = {
    "as-IN": "as",
    "bn-BD": "bn",
    "bn-IN": "bn",
    "en-AU": "en-AU",
    "en-GB": "en-GB",
    "en-HK": "en-HK",
    "en-IE": "en-IE",
    "en-IN": "en",
    "en-NZ": "en-NZ",
    "en-PH": "en-PH",
    "en-PK": "en-PK",
    "en-SG": "en-SG",
    "en-US": "en-US",
    "gu-IN": "gu",
    "hi-IN": "hi",
    "kn-IN": "kn",
    "ml-IN": "ml",
    "mr-IN": "mr",
    "ne-NP": "ne",
    "or-IN": "od",
    "pa-Guru-IN": "pa",
    "sd-IN": "sd",
    "ta-IN": "ta",
    "te-IN": "te",
    "ur-PK": "ur",
}

_TTS_LANGS = {
    "bn-IN": "bn",
    "en-AU": "en-AU",
    "en-IN": "en",
    "en-GB": "en-GB",
    "en-US": "en-US",
    "gu-IN": "gu",
    "hi-IN": "hi",
    "kn-IN": "kn",
    "ml-IN": "ml",
    "mr-IN": "mr",
    "pa-IN": "pa",
    "ta-IN": "ta",
    "te-IN": "te",
    "ur-IN": "ur",
}

_SPEED = {
    "default": 1.0,
    "minimum": 0.25,
    "maximum": 2.0,
    "input_type": "slider",
}

_TTS_FALLBACK = {
    "voice": {
        "default": None,
        "options": [],
        "input_type": "both",
        "allow_custom_input": True,
        "description": (
            "Chirp 3 HD voice ID matching the selected language locale "
            "(e.g. hi-IN-Chirp3-HD-Charon)."
        ),
    },
    "speed": dict(_SPEED),
}

STT_CAPABILITIES: dict[str, dict] = {
    model: {
        "languages": dict(_STT_LANGS),
        "settings": expand_settings(_STT_LANGS, {}),
    }
    for model in ("latest_long", "latest_short", "chirp_3")
}

_tts_settings = expand_settings(_TTS_LANGS, _TTS_FALLBACK)
_tts_settings["en-US"] = {
    "voice": {
        "default": DEFAULT_TTS_VOICE,
        "options": list(TTS_VOICES),
        "input_type": "both",
        "allow_custom_input": True,
    },
    "speed": dict(_SPEED),
}

TTS_CAPABILITIES: dict[str, dict] = {
    "chirp_3_hd": {
        "languages": dict(_TTS_LANGS),
        "settings": _tts_settings,
    },
}
