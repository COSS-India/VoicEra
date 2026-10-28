"""Maya 2 Native TTS model catalog (model-server ``tts/maya2-native`` slot).

**NOT YET RUN ON HARDWARE.** models.yaml says so for this slot.

Two things here are unlike the other local TTS providers, and both are the
model's doing:

**Each voice has its own languages.** Orpheus ties every speaker to exactly one
language; Rumik and Indic-Mio let every voice speak every language. Maya sits
between: the release's ``voices/voices.json`` lists, per voice, the languages it
had at least an hour of training data in -- eight voices cover all eleven
non-Assamese languages, and the rest cover anything from ten down to Hindi
alone. A voice outside its list still speaks (the server reports it in
``X-Voice-Untrained-Language``), but cross-lingually, so the per-language
dropdown below offers only the voices trained on that language.

**No voice lists Assamese.** The model supports it -- upstream reports a 5.4 %
CER -- but every Assamese utterance is cross-lingual, so Assamese offers the
eight broad voices rather than an empty dropdown.

**The language goes on the wire.** The other local providers let the server
read the language from the script. That cannot work here: Marathi is written
in Devanagari like Hindi, and Assamese in the Bengali script, and the model
takes a language token. So ``tts.py`` sends ``language`` with every request.

No style field: the model has no delivery conditioning, and the server reports
``instructions`` as ignored rather than acting on it.
"""

from __future__ import annotations

import os

SAMPLE_RATE = 24000

# Slot id from model-server GET /v1/models -- the folder under
# model-server/tts/. The model id is kept equal to it, as rumik_oss does.
GATEWAY_MODEL_ID = "maya2-native"
TTS_MODEL = "maya2-native"

# The eleven languages the broad voices were trained on (all but Assamese).
_BROAD: tuple[str, ...] = (
    "bn",
    "en",
    "gu",
    "hi",
    "kn",
    "ml",
    "mr",
    "or",
    "pa",
    "ta",
    "te",
)

# Voice -> languages with >= 1 h of training data, in voices.json order. Copied
# from maya-research/maya2-native voices/voices.json; GET /v1/voices on the
# running server serves the same list and is the source of truth if they ever
# disagree.
VOICE_LANGUAGES: dict[str, tuple[str, ...]] = {
    "Ahana": _BROAD,
    "Vaidehi": _BROAD,
    "Malini": _BROAD,
    "Charvi": _BROAD,
    "Jahnavi": ("bn", "en", "gu", "hi", "kn", "ml", "mr", "or", "ta", "te"),
    "Anirban": _BROAD,
    "Nakul": _BROAD,
    "Vasant": ("bn", "en", "gu", "hi", "kn", "ml", "mr", "or", "ta", "te"),
    "Siddhant": _BROAD,
    "Satvik": _BROAD,
    "Abhay": ("en", "hi"),
    "Nivedita": ("en", "hi"),
    "Ishwari": ("hi",),
    "Ritvik": ("hi",),
    "Vrinda": ("hi",),
    "Sreekar": ("en", "hi", "te"),
    "Kayal": ("en", "ta"),
    "Shaunak": ("en", "hi"),
    "Akshat": ("en", "hi"),
    "Tanushree": ("en", "hi"),
}

TTS_VOICES: tuple[str, ...] = tuple(VOICE_LANGUAGES)
DEFAULT_TTS_VOICE = "Ahana"

# Vendor language code -> VoicEra canonical id. Odia is ``or`` on the wire /
# ``od`` in VoicEra. Exactly the model's twelve (upstream maya3.server.LANGS).
_TTS_LANGS: dict[str, str] = {
    "as": "as",
    "bn": "bn",
    "en": "en",
    "gu": "gu",
    "hi": "hi",
    "kn": "kn",
    "ml": "ml",
    "mr": "mr",
    "or": "od",
    "pa": "pa",
    "ta": "ta",
    "te": "te",
}


def voices_for(vendor_lang: str) -> list[str]:
    """Voices trained on a language; for Assamese, which none are, the broad ones."""
    trained = [v for v, langs in VOICE_LANGUAGES.items() if vendor_lang in langs]
    if trained:
        return trained
    return [v for v, langs in VOICE_LANGUAGES.items() if langs == _BROAD]


def _tts_settings() -> dict[str, dict]:
    settings: dict[str, dict] = {}
    for vendor in _TTS_LANGS:
        options = voices_for(vendor)
        settings[vendor] = {
            "voice": {
                "default": DEFAULT_TTS_VOICE
                if DEFAULT_TTS_VOICE in options
                else options[0],
                "options": options,
                "input_type": "dropdown",
                "description": (
                    "Named voice. Only voices trained on this language are offered"
                    + (
                        "; no voice was trained on Assamese, so these speak it cross-lingually."
                        if vendor == "as"
                        else "."
                    )
                ),
            },
        }
    return settings


TTS_CAPABILITIES: dict[str, dict] = {
    TTS_MODEL: {
        "languages": dict(_TTS_LANGS),
        "settings": _tts_settings(),
    },
}


def resolve_wire_language(canonical: str) -> str:
    """VoicEra canonical id -> the model's code (``od`` -> ``or``); wire codes pass through."""
    code = (canonical or "").strip()
    for vendor, canon in _TTS_LANGS.items():
        if code in (canon, vendor):
            return vendor
    return code


def resolve_base_url() -> str:
    """OpenAI speech base URL (must include /v1) — required via Compose ``MODEL_SERVER_URL``."""
    url = (os.getenv("MODEL_SERVER_URL") or "").strip()
    if not url:
        raise RuntimeError("MODEL_SERVER_URL is required (set it in docker-compose)")
    return url
