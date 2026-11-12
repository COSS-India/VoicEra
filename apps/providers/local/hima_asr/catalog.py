"""Hima-ASR STT model catalog (model-server ``stt/hima-asr`` slot).

Same transport as ``indic_conformer``: OpenAI Realtime transcription at
``/v1/realtime?intent=transcription``, through Pipecat's own client. Hima-ASR
transcribes whole clips and does not stream, so the server produces partials by
re-transcribing the open segment every 600 ms -- the same mechanism, and the
same shared ``realtime_ws.py``, as Conformer.

What differs is the language set: 12 languages including English, and a model
trained for code-switched speech. The server also supports auto-detect, but this
provider always sends the agent's language, as every other STT provider does.
"""

from __future__ import annotations

import os

from ...capabilities import expand_settings

# The model decodes 16 kHz audio. The Realtime wire is 24 kHz; Pipecat
# upsamples to it and the server downsamples back, so this is informational.
SAMPLE_RATE = 16000

# Slot id from model-server GET /v1/models -- the folder under
# model-server/stt/. The model id is kept equal to it, as indic_conformer does.
GATEWAY_MODEL_ID = "hima-asr"
STT_MODEL = "hima-asr"

# Vendor language code (models.yaml ``languages``) -> VoicEra canonical id.
# Odia is ``or`` on the wire / ``od`` in VoicEra. No Bhili, no Urdu.
_STT_LANGS: dict[str, str] = {
    "hi": "hi",
    "en": "en",
    "bn": "bn",
    "ta": "ta",
    "te": "te",
    "kn": "kn",
    "ml": "ml",
    "mr": "mr",
    "gu": "gu",
    "pa": "pa",
    "or": "od",
    "as": "as",
}

STT_CAPABILITIES: dict[str, dict] = {
    STT_MODEL: {
        "languages": dict(_STT_LANGS),
        "settings": expand_settings(_STT_LANGS, {}),
    },
}


def resolve_wire_language(model: str, canonical: str) -> str:
    """Map canonical language id to the Hima-ASR wire code for the given model."""
    entry = STT_CAPABILITIES.get(model)
    if not entry:
        return canonical
    for vendor_code, canon in entry["languages"].items():
        if canon == canonical:
            return vendor_code
    return canonical


def resolve_realtime_url() -> str:
    """WS URL for ``/v1/realtime`` — required via Compose ``MODEL_SERVER_REALTIME_URL``.

    No query string: Pipecat appends ``?intent=transcription`` itself.
    """
    url = (os.getenv("MODEL_SERVER_REALTIME_URL") or "").strip()
    if not url:
        raise RuntimeError("MODEL_SERVER_REALTIME_URL is required (set it in docker-compose)")
    return url.rstrip("/")
