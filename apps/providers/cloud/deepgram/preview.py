"""Direct (non-Pipecat) TTS preview for Deepgram Aura."""

from __future__ import annotations

import httpx

from ...preview import PREVIEW_SAMPLE_RATE_HZ, pcm_to_wav, post_for_audio, register_preview
from ...registry import api_key
from .catalog import TTS_ENDPOINT
from .config import DeepgramTTSConfig


@register_preview("deepgram")
async def synthesize(cfg: DeepgramTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text``; raise :class:`PreviewProviderError` on any vendor failure."""
    # Deepgram defaults to MP3, so ask for raw linear16 explicitly. The voice id
    # is sent as ``model``, the same as the live-call service.
    params = {
        "model": cfg.voice,
        "encoding": "linear16",
        "sample_rate": PREVIEW_SAMPLE_RATE_HZ,
        "container": "none",
    }
    response = await post_for_audio(
        client,
        "Deepgram",
        TTS_ENDPOINT,
        params=params,
        json={"text": text},
        headers={"Authorization": f"Token {api_key(cfg.api_key)}"},
    )
    return pcm_to_wav(response.content, sample_rate=PREVIEW_SAMPLE_RATE_HZ)
