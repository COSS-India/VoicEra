"""Portuguese Whisper STT model catalog (model-server ``stt/pt-whisper``)."""

from __future__ import annotations

from ...capabilities import expand_settings
from ..indic_nemotron.catalog import resolve_ws_url  # same env var, same route

SAMPLE_RATE = 16000

# Slot id from model-server GET /v1/models (not the inference model name).
GATEWAY_MODEL_ID = "pt-whisper"
STT_MODEL = "pt-whisper"

# Vendor language code on the wire → VoicEra canonical id.
_STT_LANGS: dict[str, str] = {"pt": "pt-BR"}

STT_CAPABILITIES: dict[str, dict] = {
    STT_MODEL: {
        "languages": dict(_STT_LANGS),
        "settings": expand_settings(_STT_LANGS, {}),
    },
}


def resolve_wire_language(model: str, canonical: str) -> str:
    """Map canonical language id to the wire code (``pt-BR`` → ``pt``)."""
    entry = STT_CAPABILITIES.get(model)
    if not entry:
        return "pt"
    for vendor_code, canon in entry["languages"].items():
        if canon == canonical:
            return vendor_code
    return "pt"


__all__ = [
    "GATEWAY_MODEL_ID",
    "SAMPLE_RATE",
    "STT_CAPABILITIES",
    "STT_MODEL",
    "resolve_wire_language",
    "resolve_ws_url",
]
