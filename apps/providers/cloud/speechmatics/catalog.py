"""Speechmatics STT model catalog.

Speechmatics has no named acoustic model; `model` is the operating point.
"""

from ...capabilities import expand_settings

_STT_LANGS = {
    "bn": "bn",
    "en": "en",
    "hi": "hi",
    "mr": "mr",
    "ta": "ta",
    "ur": "ur",
}

STT_CAPABILITIES = {
    model: {
        "languages": dict(_STT_LANGS),
        "settings": expand_settings(_STT_LANGS, {}),
    }
    for model in ("enhanced", "standard")
}
