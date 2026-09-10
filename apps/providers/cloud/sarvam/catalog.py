"""Sarvam model catalog (STT + TTS + LLM).

All models are specialised for Indian languages.
"""

from ...capabilities import expand_settings

# --- LLM ---
# Keep in step with SarvamLLMService._SUPPORTED_MODELS in pipecat.
# Do NOT add a model here that the service rejects — it causes hard failures at pipeline start.
LLM_MODELS: tuple[str, ...] = ("sarvam-105b",)
DEFAULT_LLM_MODEL = "sarvam-105b"

# --- STT ---
_SAARIKA_LANGUAGES = {
    "unknown": "multi",
    "hi-IN": "hi",
    "bn-IN": "bn",
    "gu-IN": "gu",
    "kn-IN": "kn",
    "ml-IN": "ml",
    "mr-IN": "mr",
    "od-IN": "od",
    "pa-IN": "pa",
    "ta-IN": "ta",
    "te-IN": "te",
    "en-IN": "en",
}

_SAARAS_LANGUAGES = {
    "unknown": "multi",
    "hi-IN": "hi",
    "bn-IN": "bn",
    "gu-IN": "gu",
    "kn-IN": "kn",
    "ml-IN": "ml",
    "mr-IN": "mr",
    "od-IN": "od",
    "pa-IN": "pa",
    "ta-IN": "ta",
    "te-IN": "te",
    "en-IN": "en",
    "as-IN": "as",
    "ur-IN": "ur",
    "ne-IN": "ne",
    "kok-IN": "kok",
    "ks-IN": "ks",
    "sd-IN": "sd",
    "sa-IN": "sa",
    "sat-IN": "sat",
    "mni-IN": "mni",
    "brx-IN": "brx",
    "mai-IN": "mai",
    "doi-IN": "doi",
}

STT_CAPABILITIES = {
    "saarika:v2.5": {
        "languages": _SAARIKA_LANGUAGES,
        "settings": expand_settings(_SAARIKA_LANGUAGES, {}),
    },
    "saaras:v3": {
        "languages": _SAARAS_LANGUAGES,
        "settings": expand_settings(_SAARAS_LANGUAGES, {}),
    },
}

# --- TTS ---
DEFAULT_TTS_V3_VOICE = "shubh"

# Bulbul v3 voices (extended set)
TTS_V3_VOICES: tuple[str, ...] = (
    "shubh", "aditya", "ritu", "priya", "neha", "rahul", "pooja",
    "rohan", "simran", "kavya", "amit", "dev", "ishita", "shreya",
    "ratan", "varun", "manan", "sumit", "roopa", "kabir", "aayan",
    "ashutosh", "advait", "amelia", "sophia", "anand", "tanya",
    "tarun", "sunny", "mani", "gokul", "vijay", "shruti", "suhani",
    "mohit", "kavitha", "rehan", "soham", "rupali",
)

_BULBUL_LANGUAGES = {
    "bn-IN": "bn",
    "en-IN": "en",
    "gu-IN": "gu",
    "hi-IN": "hi",
    "kn-IN": "kn",
    "ml-IN": "ml",
    "mr-IN": "mr",
    "od-IN": "od",
    "pa-IN": "pa",
    "ta-IN": "ta",
    "te-IN": "te",
    "as-IN": "as",
}

_TTS_SPEED = {
    "default": 1.0,
    "minimum": 0.5,
    "maximum": 2.0,
    "input_type": "slider",
}

TTS_CAPABILITIES = {
    "bulbul:v3": {
        "languages": _BULBUL_LANGUAGES,
        "settings": expand_settings(
            _BULBUL_LANGUAGES,
            {
                "voice": {
                    "default": DEFAULT_TTS_V3_VOICE,
                    "options": list(TTS_V3_VOICES),
                    "input_type": "both",
                    "allow_custom_input": True,
                },
                "speed": dict(_TTS_SPEED),
            },
        ),
    },
}
