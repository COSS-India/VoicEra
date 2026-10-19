"""Direct (non-Pipecat) TTS preview for xAI."""

from __future__ import annotations

import httpx

from ...preview import PREVIEW_SAMPLE_RATE_HZ, pcm_to_wav, post_for_audio, register_preview, resolve_wire_language
from ...registry import api_key
from .catalog import TTS_CAPABILITIES, TTS_ENDPOINT
from .config import XAITTSConfig


@register_preview("xai")
async def synthesize(cfg: XAITTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text``; raise :class:`PreviewProviderError` on any vendor failure."""
    payload = {
        "text": text,
        "voice_id": cfg.voice,
        "output_format": {"codec": "pcm", "sample_rate": PREVIEW_SAMPLE_RATE_HZ},
        # xAI requires a language; canonical "multi" maps to its "auto".
        "language": resolve_wire_language(TTS_CAPABILITIES, cfg.model, cfg.language),
    }
    response = await post_for_audio(
        client,
        "xAI",
        TTS_ENDPOINT,
        json=payload,
        headers={"Authorization": f"Bearer {api_key(cfg.api_key)}"},
    )
    return pcm_to_wav(response.content, sample_rate=PREVIEW_SAMPLE_RATE_HZ)
