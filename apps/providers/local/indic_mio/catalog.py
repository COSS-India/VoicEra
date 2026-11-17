"""Indic-Mio TTS model catalog (model-server ``tts/indic-mio`` slot).

**NOT YET RUN ON HARDWARE.** models.yaml says so for this slot, and nothing in
this catalog has been heard on a live deployment. Treat the language list in
particular as the model card's claim, not a measurement.

How it differs from the other local TTS providers, all of it the model's doing:

**The voice is a speaker embedding, and it carries the accent.** There is no
description and no style: the server accepts ``instructions`` for contract
parity and ignores it, so this provider has no ``style`` field at all rather
than one that silently does nothing. ``language`` is informational too -- the
model reads it from the text's script. What changes how a line sounds is
which of the five embeddings is chosen, and each was built from one AI4Bharat
Rasa recording in one language (``model-server/tts/indic-mio/voices/
manifest.json``). So every voice speaks every language, as Rumik's do, but
with the accent of the language it was recorded in. The per-language default
below is the voice recorded in that language where there is one.

**44.1 kHz,** like Parler. The native wire is float32; this provider asks for
``pcm`` (signed 16-bit), which the server converts to.

Emotion and stress are tags in the text itself (``<happy>``, ``*word*``) per the
upstream README. Nothing here adds them; the LLM's text goes through as is.
"""

from __future__ import annotations

import os

# models.yaml and the slot's DEFAULT_SAMPLE_RATE. The server takes the real
# value from the codec at load and reports it in X-Sample-Rate; tts.py logs a
# mismatch.
SAMPLE_RATE = 44100

# Slot id from model-server GET /v1/models -- the folder under
# model-server/tts/. The model id is kept equal to it, as rumik_oss does.
GATEWAY_MODEL_ID = "indic-mio"
TTS_MODEL = "indic-mio"

# The server's own roster (voices/manifest.json, also GET /v1/voices), in its
# order. Aditi is the manifest's default.
TTS_VOICES: tuple[str, ...] = ("Aditi", "Meera", "Ananya", "Rahul", "Arjun")
DEFAULT_TTS_VOICE = "Aditi"

# Vendor language code -> VoicEra canonical id. The model card claims "22
# scheduled Indian languages + English" without enumerating them, so these are
# the 22 Eighth Schedule languages plus English. Unverified on hardware: see
# the module docstring. Odia is ``or`` on the wire / ``od`` in VoicEra.
_TTS_LANGS: dict[str, str] = {
    "as": "as",
    "bn": "bn",
    "brx": "brx",
    "doi": "doi",
    "gu": "gu",
    "hi": "hi",
    "kn": "kn",
    "kok": "kok",
    "ks": "ks",
    "mai": "mai",
    "ml": "ml",
    "mni": "mni",
    "mr": "mr",
    "ne": "ne",
    "or": "od",
    "pa": "pa",
    "sa": "sa",
    "sat": "sat",
    "sd": "sd",
    "ta": "ta",
    "te": "te",
    "ur": "ur",
    "en": "en",
}

# The language each voice's reference clip was recorded in (manifest
# ``source``). Hindi has two; Aditi wins as the manifest default.
_NATIVE_VOICE: dict[str, str] = {
    "hi": "Aditi",
    "ta": "Meera",
    "bn": "Ananya",
    "te": "Arjun",
}


def _tts_settings() -> dict[str, dict]:
    settings: dict[str, dict] = {}
    for vendor in _TTS_LANGS:
        settings[vendor] = {
            "voice": {
                "default": _NATIVE_VOICE.get(vendor, DEFAULT_TTS_VOICE),
                "options": list(TTS_VOICES),
                "input_type": "dropdown",
                "description": (
                    "Speaker embedding. Every voice speaks every language, with the "
                    "accent of the language it was recorded in: Aditi and Rahul "
                    "Hindi, Meera Tamil, Ananya Bengali, Arjun Telugu."
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
