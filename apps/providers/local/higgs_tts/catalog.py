"""Higgs TTS 3 model catalog (model-server ``tts/higgs-tts-3`` slot).

**Licence: Boson Higgs TTS 3 Research and Non-Commercial License.** Research
and non-commercial use only; a product, hosted API or resale needs a
commercial licence from Boson. VoicEra deploys it as a DPG. See
``model-server/tts/higgs-tts-3/README.md``.

**NOT YET RUN ON HARDWARE**, and the voices' reference clips are not in the repo
yet (they are fetched once from the gated ai4bharat/Rasa dataset and
committed). Until they are, the slot's /health is 503 and readiness checks
report this provider unavailable -- which is the truth.

How it differs from the other local TTS providers, all of it the model's doing:

**A voice is a reference clip, and it carries the accent.** Higgs has no
built-in speakers; the server clones each voice zero-shot from a clip plus its
transcript. These are the same five AI4Bharat Rasa speakers as ``indic_mio``,
so every voice speaks every language here with the accent of the language it
was recorded in, and the per-language default is the voice recorded in that
language where there is one.

**The style is a FIXED list of the model's own control tags.** Rumik and Parler
take free text; Higgs takes ``<|emotion:...|>`` style tags and reads anything
else aloud or degrades, so the server refuses free text with a 400. ``style``
is therefore a dropdown with no custom input, and ``none`` -- plain delivery --
is the default. The list is the server's own (``tags.py``);
``tests/test_higgs_tts.py`` keeps the two from drifting.

**Fewer languages than the other Indic models.** Boson's tier 1 Indic set plus
English, and Punjabi from tier 2. Sindhi (tier 2) is held back until someone
has listened to it; Odia, Sanskrit, Bodo, Dogri, Konkani, Kashmiri, Maithili,
Manipuri and Santali are not supported, so they are not offered -- an agent
configured for one would get nonsense with nothing logged.
"""

from __future__ import annotations

import os

SAMPLE_RATE = 24000

# Slot id from model-server GET /v1/models -- the folder under
# model-server/tts/. The model id is kept equal to it, as rumik_oss does.
GATEWAY_MODEL_ID = "higgs-tts-3"
TTS_MODEL = "higgs-tts-3"

# The server's roster (voices/manifest.json, also GET /v1/voices), in its order.
TTS_VOICES: tuple[str, ...] = ("Aditi", "Meera", "Ananya", "Rahul", "Arjun")
DEFAULT_TTS_VOICE = "Aditi"

# Vendor code -> VoicEra canonical id. The model reads the language from the
# text's script; these are the languages Boson reports single-digit WER/CER for.
_TTS_LANGS: dict[str, str] = {
    "hi": "hi",
    "bn": "bn",
    "ta": "ta",
    "te": "te",
    "kn": "kn",
    "ml": "ml",
    "mr": "mr",
    "gu": "gu",
    "as": "as",
    "ne": "ne",
    "ur": "ur",
    "pa": "pa",
    "en": "en",
}

# The language each voice's clip was recorded in (manifest ``language``).
_NATIVE_VOICE: dict[str, str] = {
    "hi": "Aditi",
    "ta": "Meera",
    "bn": "Ananya",
    "te": "Arjun",
}

#: Plain delivery: no control tags. The server's word for it.
NO_STYLE = "none"

#: Every value the server's ``instructions`` accepts as one choice, in its
#: ``category:value`` spelling: model-server/tts/higgs-tts-3/tags.py.
_EMOTIONS = (
    "affection", "amusement", "anger", "arousal", "awe", "bitterness", "confusion",
    "contemplation", "contentment", "determination", "disgust", "elation",
    "enthusiasm", "fear", "helplessness", "longing", "pride", "relief", "sadness",
    "shame", "surprise",
)
_STYLES = ("singing", "shouting", "whispering")
_PROSODY = (
    "speed_very_slow", "speed_slow", "speed_fast", "speed_very_fast",
    "pitch_low", "pitch_high", "expressive_high", "expressive_low",
)
TTS_STYLES: tuple[str, ...] = (
    NO_STYLE,
    *(f"emotion:{v}" for v in _EMOTIONS),
    *(f"style:{v}" for v in _STYLES),
    *(f"prosody:{v}" for v in _PROSODY),
)
DEFAULT_TTS_STYLE = NO_STYLE


def _tts_settings() -> dict[str, dict]:
    settings: dict[str, dict] = {}
    for vendor in _TTS_LANGS:
        settings[vendor] = {
            "voice": {
                "default": _NATIVE_VOICE.get(vendor, DEFAULT_TTS_VOICE),
                "options": list(TTS_VOICES),
                "input_type": "dropdown",
                "description": (
                    "Reference voice. Every voice speaks every language, with the "
                    "accent of the language it was recorded in: Aditi and Rahul "
                    "Hindi, Meera Tamil, Ananya Bengali, Arjun Telugu."
                ),
            },
            "style": {
                "default": DEFAULT_TTS_STYLE,
                "options": list(TTS_STYLES),
                "input_type": "dropdown",
                "allow_custom_input": False,
                "description": (
                    "Delivery, as one of the model's own control tags: an emotion, a "
                    "style, or a prosody change. 'none' is plain delivery. Free text "
                    "is not accepted -- the model would read it aloud."
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


def resolve_base_url() -> str:
    """OpenAI speech base URL (must include /v1) — required via Compose ``MODEL_SERVER_URL``."""
    url = (os.getenv("MODEL_SERVER_URL") or "").strip()
    if not url:
        raise RuntimeError("MODEL_SERVER_URL is required (set it in docker-compose)")
    return url
