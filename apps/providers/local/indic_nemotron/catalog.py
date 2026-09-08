"""Indic Nemotron STT model catalog (model-server indic-nemotron)."""

from __future__ import annotations

import os

from ...capabilities import expand_settings

SAMPLE_RATE = 16000

# Slot id from model-server GET /v1/models (not the inference model name).
GATEWAY_MODEL_ID = "indic-nemotron"
STT_MODEL = "indic-nemotron-600m"

# Vendor language code (Nemotron LANGUAGE_PROMPT_MAP) → VoicEra canonical id.
# Odia is ``or`` on the wire / ``od`` in VoicEra; Bhili is ``bhb`` / ``bh``.
_STT_LANGS: dict[str, str] = {
    "hi": "hi",
    "mr": "mr",
    "bn": "bn",
    "ta": "ta",
    "te": "te",
    "gu": "gu",
    "kn": "kn",
    "ml": "ml",
    "pa": "pa",
    "or": "od",
    "as": "as",
    "ur": "ur",
    "sa": "sa",
    "ne": "ne",
    "sd": "sd",
    "mai": "mai",
    "doi": "doi",
    "kok": "kok",
    "brx": "brx",
    "mni": "mni",
    "sat": "sat",
    "ks": "ks",
    "bho": "bho",
    "hne": "hne",
    "bgc": "bgc",
    "bhb": "bh",
    "en": "en",
}

STT_CAPABILITIES: dict[str, dict] = {
    STT_MODEL: {
        "languages": dict(_STT_LANGS),
        "settings": expand_settings(_STT_LANGS, {}),
    },
}


def resolve_wire_language(model: str, canonical: str) -> str:
    """Map canonical language id to Nemotron wire code for the given model."""
    entry = STT_CAPABILITIES.get(model)
    if not entry:
        return canonical
    for vendor_code, canon in entry["languages"].items():
        if canon == canonical:
            return vendor_code
    return canonical


def resolve_ws_url() -> str:
    """Full WS URL for ``/v1/asr/ws`` — required via Compose ``MODEL_SERVER_WS_URL``."""
    url = (os.getenv("MODEL_SERVER_WS_URL") or "").strip()
    if not url:
        raise RuntimeError("MODEL_SERVER_WS_URL is required (set it in docker-compose)")
    return url
