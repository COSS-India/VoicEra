"""Direct (non-Pipecat) TTS preview for Inworld."""

from __future__ import annotations

import base64

import httpx

from ...preview import (
    PREVIEW_SAMPLE_RATE_HZ,
    PreviewProviderError,
    pcm_to_wav,
    post_for_audio,
    register_preview,
    resolve_wire_language,
)
from .catalog import TTS_CAPABILITIES, TTS_ENDPOINT
from .config import InworldTTSConfig

_WAV_HEADER_BYTES = 44


@register_preview("inworld")
async def synthesize(cfg: InworldTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text``; raise :class:`PreviewProviderError` on any vendor failure."""
    payload = {
        "text": text,
        "voiceId": cfg.voice,
        "modelId": cfg.model,
        # Headerless PCM, as the live-call service requests.
        "audioConfig": {"audioEncoding": "PCM", "sampleRateHertz": PREVIEW_SAMPLE_RATE_HZ, "speakingRate": cfg.speed},
        "deliveryMode": cfg.delivery_mode,
        "language": resolve_wire_language(TTS_CAPABILITIES, cfg.model, cfg.language),
    }
    response = await post_for_audio(
        client,
        "Inworld",
        TTS_ENDPOINT,
        json=payload,
        # The Inworld key is already the base64 credential Basic auth expects.
        headers={"Authorization": f"Basic {cfg.api_key}"},
    )
    try:
        pcm = base64.b64decode(response.json()["audioContent"])
    except (ValueError, LookupError, TypeError) as exc:
        raise PreviewProviderError("Inworld preview returned a malformed response") from exc
    # Inworld sometimes prefixes PCM with a WAV header; pipecat strips it too.
    # A header with no frames strips to empty and fails the check below.
    if pcm.startswith(b"RIFF") and len(pcm) >= _WAV_HEADER_BYTES:
        pcm = pcm[_WAV_HEADER_BYTES:]
    if not pcm:
        raise PreviewProviderError("Inworld preview returned no audio")
    return pcm_to_wav(pcm, sample_rate=PREVIEW_SAMPLE_RATE_HZ)
