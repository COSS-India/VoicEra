"""Direct (non-Pipecat) TTS preview for self-hosted Indic Orpheus."""

from __future__ import annotations

import httpx

from ...preview import PreviewProviderError, pcm_to_wav, post_for_audio, register_preview
from .catalog import SAMPLE_RATE, resolve_base_url
from .config import IndicOrpheusTTSConfig

# Same headerless PCM the live-call service streams; wrapped at the native rate.
_RESPONSE_FORMAT = "pcm"


@register_preview("indic_orpheus")
async def synthesize(cfg: IndicOrpheusTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text``; raise :class:`PreviewProviderError` on any server failure."""
    try:
        base_url = resolve_base_url()
    except RuntimeError as exc:
        raise PreviewProviderError("Indic Orpheus preview: MODEL_SERVER_URL is not set") from exc
    payload = {"input": text, "model": cfg.model, "voice": cfg.voice, "response_format": _RESPONSE_FORMAT}
    if style := cfg.style.strip():
        payload["instructions"] = style
    # The gateway has no auth (the live-call service sends a dummy key too).
    response = await post_for_audio(client, "Indic Orpheus", f"{base_url.rstrip('/')}/audio/speech", json=payload)
    return pcm_to_wav(response.content, sample_rate=SAMPLE_RATE)
