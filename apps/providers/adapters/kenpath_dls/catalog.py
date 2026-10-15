"""Kenpath DLS (Vistaar voice-dls) LLM catalog."""

from __future__ import annotations

DEFAULT_URL = "https://vistaar-dev.mahapocra.gov.in"
VOICE_DLS_PATH = "/api/voice-dls/"

DEFAULT_LLM_MODEL = "vistaar-dls (Marathi, Bhili)"
LLM_MODELS: tuple[str, ...] = (DEFAULT_LLM_MODEL,)

# Canonical language ids for agent stacks (wire Bhili is ``bhb``).
DLS_LANGUAGES: tuple[str, ...] = ("mr", "bh")

# Config secret field used to sign JWTs (same Vistaar PEM as Kenpath ``/api/voice/``).
VISTAAR_AUTH_SECRET = "private_key"


def resolve_base_url(override: str | None = None) -> str:
    if override:
        return override.rstrip("/")
    return DEFAULT_URL.rstrip("/")
