"""Indic Conformer STT model catalog (model-server ``stt/indic-conformer`` slot).

Unlike ``indic_nemotron``, this model does not serve ``/v1/asr/ws``. It serves
OpenAI Realtime transcription at ``/v1/realtime?intent=transcription`` -- the
protocol the STT slot standardises on -- and its server was written against
Pipecat's ``OpenAIRealtimeSTTService``. So there is no hand-written wire client
here, only a thin subclass in ``stt.py``.

Partials still arrive mid-utterance: the server re-transcribes the open segment
every 600 ms and emits the settled words as Realtime deltas. The cost of that,
compared with Nemotron's incremental decode, is GPU work that grows with
utterance length, not latency the caller hears.
"""

from __future__ import annotations

import os

from ...capabilities import expand_settings

# The model decodes 16 kHz audio. The Realtime wire is 24 kHz; Pipecat
# upsamples to it and the server downsamples back, so this is informational.
SAMPLE_RATE = 16000

# Slot id from model-server GET /v1/models -- the folder under
# model-server/stt/. The model id is kept equal to it, as rumik_oss does.
GATEWAY_MODEL_ID = "indic-conformer"
STT_MODEL = "indic-conformer"

# Vendor language code (models.yaml ``languages``) -> VoicEra canonical id.
# Odia is ``or`` on the wire / ``od`` in VoicEra; Bhili is ``bhb`` / ``bh``.
#
# BHILI IS CONDITIONAL. It runs on a second checkpoint the server loads only
# with BHILI_ENABLE=yes. Without it the server fails every Bhili turn with
# "Bhili model is disabled" -- logged by Pipecat as a transcription failure, so
# a misconfigured deployment is visible rather than silent. The provider cannot
# see the server's environment, so it is listed and this note is the caveat.
#
# No English, and no auto-detect: the checkpoint is Indic-only and the server
# transcribes in whatever language the session names.
_STT_LANGS: dict[str, str] = {
    "hi": "hi",
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
    "ur": "ur",
    "ne": "ne",
    "sa": "sa",
    "brx": "brx",
    "doi": "doi",
    "kok": "kok",
    "ks": "ks",
    "mai": "mai",
    "mni": "mni",
    "sat": "sat",
    "sd": "sd",
    "bhb": "bh",
}

STT_CAPABILITIES: dict[str, dict] = {
    STT_MODEL: {
        "languages": dict(_STT_LANGS),
        "settings": expand_settings(_STT_LANGS, {}),
    },
}


def resolve_wire_language(model: str, canonical: str) -> str:
    """Map canonical language id to the Conformer wire code for the given model."""
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
