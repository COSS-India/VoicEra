"""AssemblyAI model catalog."""

from ...capabilities import expand_settings

_STT_LANGS = {
    "en": "en",
}

STT_CAPABILITIES = {
    "u3-rt-pro": {
        "languages": dict(_STT_LANGS),
        "settings": expand_settings(_STT_LANGS, {}),
    },
}
