"""Gladia model catalog (STT)."""

from ...capabilities import expand_settings

_STT_LANGS = {
    "as": "as",
    "bn": "bn",
    "en": "en",
    "gu": "gu",
    "hi": "hi",
    "kn": "kn",
    "ml": "ml",
    "mr": "mr",
    "ne": "ne",
    "pa": "pa",
    "sa": "sa",
    "sd": "sd",
    "ta": "ta",
    "te": "te",
    "ur": "ur",
}

STT_CAPABILITIES = {
    "solaria-1": {
        "languages": dict(_STT_LANGS),
        "settings": expand_settings(_STT_LANGS, {}),
    },
}
