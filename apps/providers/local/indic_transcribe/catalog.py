"""Indic Transcribe STT model catalog (model-server ``stt/indic-transcribe`` slot).

Same transport as ``indic_conformer``: OpenAI Realtime transcription at
``/v1/realtime?intent=transcription``, through Pipecat's own client. The model
also serves ``/v1/asr/ws``, but that is its older native protocol -- different
from Nemotron's despite the shared path -- and the server keeps it only "while
/v1/realtime is proven". The Realtime route has the same decoder, turn handling
and rotation safeguards; only the envelopes differ.

What this model does differently is decode incrementally (AlignAtt), so each
new word costs one word rather than a re-transcription of the segment. A
``session.update`` that changes language replaces the turn, because a turn's
prompt fixes its language. Server-side endpointing is off unless the URL asks
for it, which this provider does not: Silero ends the turn.

The checkpoint lives in a private HuggingFace repo; a deployment needs a token
with read access before this provider can ever show as available.
"""

from __future__ import annotations

import os

from ...capabilities import expand_settings

# The model decodes 16 kHz audio. The Realtime wire is 24 kHz; Pipecat
# upsamples to it and the server downsamples back, so this is informational.
SAMPLE_RATE = 16000

# Slot id from model-server GET /v1/models -- the folder under
# model-server/stt/. The model id is kept equal to it, as rumik_oss does.
GATEWAY_MODEL_ID = "indic-transcribe"
STT_MODEL = "indic-transcribe"

# Vendor language code -> VoicEra canonical id. These are the 25 the server
# names in app.py (NAMES/SCRIPTS), which its README says match the checkpoint's
# own tokenizer_config.json and GET /v1/languages: the 22 Eighth Schedule
# languages plus Bhojpuri, Bhili and Indian English. Not the 27 in upstream's
# LANGUAGES tuple -- ``bgc`` and ``hne`` are advertised there but absent from
# the vocabulary. Unlike Conformer, the server validates the language and
# rejects one it does not have with a readable error.
#
# Odia is ``or`` on the wire / ``od`` in VoicEra; Bhili is ``bhb`` / ``bh``.
# No auto-detect: a wrong language yields confident output in the wrong script.
_STT_LANGS: dict[str, str] = {
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
    "bho": "bho",
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
    """Map canonical language id to the Indic Transcribe wire code for the given model."""
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
