"""Direct (non-Pipecat) TTS preview for Cartesia Sonic."""

from __future__ import annotations

import httpx

from ...preview import post_for_audio, register_preview, resolve_preview_sample_rate, resolve_wire_language
from .catalog import API_VERSION, TTS_CAPABILITIES, TTS_ENDPOINT
from .config import CartesiaTTSConfig


@register_preview("cartesia")
async def synthesize(cfg: CartesiaTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text``; raise :class:`PreviewProviderError` on any vendor failure."""
    payload = {
        "model_id": cfg.model,
        "transcript": text,
        "voice": {"mode": "id", "id": cfg.voice},
        "language": resolve_wire_language(TTS_CAPABILITIES, cfg.model, cfg.language),
        "output_format": {
            "container": "wav",
            "encoding": "pcm_s16le",
            "sample_rate": resolve_preview_sample_rate(cfg),
        },
        "generation_config": {"speed": cfg.speed, "volume": cfg.volume},
    }
    response = await post_for_audio(
        client,
        "Cartesia",
        TTS_ENDPOINT,
        json=payload,
        headers={"X-API-Key": cfg.api_key, "Cartesia-Version": API_VERSION},
    )
    return response.content
