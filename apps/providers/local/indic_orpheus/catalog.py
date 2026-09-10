"""Indic Orpheus TTS model catalog (model-server Orpheus ``voices-v2.json`` roster)."""

from __future__ import annotations

import os

SAMPLE_RATE = 24000

# Slot id from model-server GET /v1/models (not the inference model name).
GATEWAY_MODEL_ID = "orpheus"
TTS_MODEL = "orpheus-indic"

DEFAULT_TTS_VOICE = "Amit"
# v2 styles (voices-v2.json). Do not use v1 CONV/WIKI/NEWS — different vocabulary.
DEFAULT_TTS_STYLE = "news"

TTS_STYLES: tuple[str, ...] = (
    "news",
    "AIR style news",
    "TV style news",
    "educational lecture",
    "single person narration audiobook",
    "children's stories",
    "advertisements",
    "Customer Care",
    "happy",
    "sad",
    "anger",
    "fear",
    "surprise",
    "disgust",
)

# Orpheus vendor language code → speakers (voices-v2.json).
# Speaker name uniquely implies language on the wire.
TTS_SPEAKERS: dict[str, tuple[str, ...]] = {
    "as": ("Prastuti", "Ankur"),
    "bn": ("Ishita", "Sourav"),
    "bhb": ("Bhima", "Dhulji", "Govind", "Jhamku", "Kanku", "Sarju", "Tantya"),
    "brx": ("Gwrbw", "Sansuma"),
    "doi": ("Preeti", "Sham"),
    "gu": ("Dhara", "Parth"),
    "hi": ("Kavya", "Amit"),
    "kn": ("Deepika", "Adarsh"),
    "ks": ("Zoon", "Ishfaq"),
    "kok": ("Anjali", "Sandeep"),
    "mai": ("Vaidehi", "Madhukar"),
    "ml": ("Lakshmi", "Kiran"),
    "mni": ("Thoibi", "Chaoba"),
    "mr": ("Anagha", "Chinmay"),
    "ne": ("Srijana", "Sagar"),
    "or": ("Itishree", "Akash"),
    "pa": ("Kaur", "Manpreet"),
    "sa": ("Bharati", "Aryaman"),
    "sat": ("Phulmani", "Sibu"),
    "sd": ("Moomal", "Rano"),
    "ta": ("Anitha", "Arun"),
    "te": ("Sravani", "Vamsi"),
    "ur": ("Saba", "Zaid"),
    "en": ("Kavya", "Amit"),
}

# Vendor language code → VoicEra canonical id (``or`` → ``od``, ``bhb`` → ``bh``).
_TTS_LANGS: dict[str, str] = {
    "as": "as",
    "bn": "bn",
    "bhb": "bh",
    "brx": "brx",
    "doi": "doi",
    "gu": "gu",
    "hi": "hi",
    "kn": "kn",
    "ks": "ks",
    "kok": "kok",
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


def _style_meta() -> dict:
    return {
        "default": DEFAULT_TTS_STYLE,
        "options": list(TTS_STYLES),
        "input_type": "dropdown",
        "description": "Speaking style sent as OpenAI TTS instructions (Orpheus v2 roster).",
    }


def _tts_settings() -> dict[str, dict]:
    settings: dict[str, dict] = {}
    for vendor, speakers in TTS_SPEAKERS.items():
        settings[vendor] = {
            "voice": {
                "default": speakers[0]
                if DEFAULT_TTS_VOICE not in speakers
                else DEFAULT_TTS_VOICE,
                "options": list(speakers),
                "input_type": "dropdown",
                "description": "Speaker name; uniquely selects the language on Orpheus.",
            },
            "style": _style_meta(),
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
