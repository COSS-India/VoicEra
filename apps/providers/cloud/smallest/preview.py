"""Direct (non-Pipecat) TTS preview for Smallest.ai Lightning."""

from __future__ import annotations

import httpx

from ...preview import (
    pcm_to_wav,
    post_for_audio,
    register_preview,
    resolve_preview_sample_rate,
    resolve_wire_language,
)
from .catalog import TTS_CAPABILITIES, TTS_ENDPOINT
from .config import SmallestTTSConfig


@register_preview("smallest")
async def synthesize(cfg: SmallestTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text``; raise :class:`PreviewProviderError` on any vendor failure."""
    # The user's own sample rate, so the preview lets them hear that choice.
    sample_rate = resolve_preview_sample_rate(cfg)
    payload = {
        "text": text,
        "voice_id": cfg.voice,
        "model": cfg.model,
        "language": resolve_wire_language(TTS_CAPABILITIES, cfg.model, cfg.language),
        "sample_rate": sample_rate,
        "speed": cfg.speed,
        "output_format": "pcm",
    }
    response = await post_for_audio(
        client,
        "Smallest",
        TTS_ENDPOINT,
        json=payload,
        headers={"Authorization": f"Bearer {cfg.api_key}"},
    )
    return pcm_to_wav(response.content, sample_rate=sample_rate)
