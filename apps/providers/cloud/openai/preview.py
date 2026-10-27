"""Direct (non-Pipecat) TTS preview for OpenAI."""

from __future__ import annotations

import httpx

from ...preview import post_for_audio, register_preview
from ...registry import api_key
from .catalog import TTS_ENDPOINT
from .config import OpenAITTSConfig

# OpenAI's WAV is 24 kHz; the header carries the rate, so no resampling.
_RESPONSE_FORMAT = "wav"


@register_preview("openai")
async def synthesize(cfg: OpenAITTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text``; raise :class:`PreviewProviderError` on any vendor failure."""
    response = await post_for_audio(
        client,
        "OpenAI",
        TTS_ENDPOINT,
        json={"model": cfg.model, "voice": cfg.voice, "input": text, "response_format": _RESPONSE_FORMAT},
        headers={"Authorization": f"Bearer {api_key(cfg.api_key)}"},
    )
    return response.content
