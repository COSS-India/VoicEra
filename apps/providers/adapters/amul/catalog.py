"""Amul dev voice LLM catalog."""

from __future__ import annotations

DEFAULT_URL = "https://voice.dev.amulai.in"
VOICE_PATH = "/api/voice/"

DEFAULT_LLM_MODEL = "amul-dev (English, Gujarati)"
LLM_MODELS: tuple[str, ...] = (DEFAULT_LLM_MODEL,)

# Fixed for the shared dev eval farmer. Not agent-config fields.
DEFAULT_SOURCE_LANG = "gu"
DEFAULT_USER_ID = "5550000001"


def resolve_base_url(override: str | None = None) -> str:
    if override:
        return override.rstrip("/")
    return DEFAULT_URL.rstrip("/")
