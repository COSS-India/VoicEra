"""Deepgram model catalog (STT and TTS)."""

from ...capabilities import expand_settings

# --- STT languages ---
_NOVA = {
    "multi": "multi",
    "bn": "bn",
    "en": "en",
    "en-US": "en-US",
    "en-AU": "en-AU",
    "en-GB": "en-GB",
    "en-IN": "en",
    "en-NZ": "en-NZ",
    "hi": "hi",
    "kn": "kn",
    "mr": "mr",
    "ta": "ta",
    "te": "te",
    "ur": "ur",
}

_FLUX_EN = {"en": "en"}

_FLUX_MULTI = {
    "multi": "multi",
    "en": "en",
    "hi": "hi",
}

STT_CAPABILITIES: dict[str, dict] = {
    "nova-3-general": {
        "languages": dict(_NOVA),
        "settings": expand_settings(_NOVA, {}),
    },
    "nova-3-medical": {
        "languages": dict(_NOVA),
        "settings": expand_settings(_NOVA, {}),
    },
    "flux-general-en": {
        "languages": _FLUX_EN,
        "settings": expand_settings(_FLUX_EN, {}),
    },
    "flux-general-multi": {
        "languages": _FLUX_MULTI,
        "settings": expand_settings(_FLUX_MULTI, {}),
    },
}

# --- TTS ---
# Pipecat sends the voice ID as the Deepgram "model" query param.
# Aura-2 ids use aura-2-<name>-en; Aura-1 (legacy) ids use aura-<name>-en.
TTS_AURA2_VOICES: tuple[str, ...] = (
    "aura-2-helena-en",
    "aura-2-asteria-en",
    "aura-2-luna-en",
    "aura-2-stella-en",
    "aura-2-athena-en",
    "aura-2-hera-en",
    "aura-2-orion-en",
    "aura-2-arcas-en",
    "aura-2-perseus-en",
    "aura-2-angus-en",
    "aura-2-orpheus-en",
    "aura-2-helios-en",
    "aura-2-zeus-en",
)

# Curated Aura-1 English voices (Deepgram docs).
TTS_AURA1_VOICES: tuple[str, ...] = (
    "aura-asteria-en",
    "aura-luna-en",
    "aura-stella-en",
    "aura-athena-en",
    "aura-hera-en",
    "aura-orion-en",
    "aura-arcas-en",
    "aura-perseus-en",
    "aura-angus-en",
    "aura-orpheus-en",
    "aura-helios-en",
    "aura-zeus-en",
)

TTS_VOICES: tuple[str, ...] = TTS_AURA2_VOICES

DEFAULT_TTS_VOICE = "aura-2-helena-en"
DEFAULT_TTS_AURA1_VOICE = "aura-asteria-en"

_TTS_LANGUAGES = {"en": "en"}

TTS_CAPABILITIES: dict[str, dict] = {
    "aura-2": {
        "languages": dict(_TTS_LANGUAGES),
        "settings": {
            "en": {
                "voice": {
                    "default": DEFAULT_TTS_VOICE,
                    "options": list(TTS_AURA2_VOICES),
                    "input_type": "both",
                    "allow_custom_input": True,
                },
            },
        },
    },
    "aura-1": {
        "languages": dict(_TTS_LANGUAGES),
        "settings": {
            "en": {
                "voice": {
                    "default": DEFAULT_TTS_AURA1_VOICE,
                    "options": list(TTS_AURA1_VOICES),
                    "input_type": "both",
                    "allow_custom_input": True,
                },
            },
        },
    },
}
