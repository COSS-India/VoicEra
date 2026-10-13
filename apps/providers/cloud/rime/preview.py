"""Direct (non-Pipecat) TTS preview for Rime."""

from __future__ import annotations

import httpx

from ...preview import PREVIEW_SAMPLE_RATE_HZ, pcm_to_wav, post_for_audio, register_preview
from .catalog import TTS_ENDPOINT
from .config import RimeTTSConfig

# Rime takes ISO 639-3 codes; the live call gets these from pipecat's
# language_to_rime_language. Unknown ids pass through as-is, as pipecat does.
_RIME_LANGUAGES = {"en": "eng", "hi": "hin"}


@register_preview("rime")
async def synthesize(cfg: RimeTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text``; raise :class:`PreviewProviderError` on any vendor failure."""
    payload = {
        "text": text,
        "speaker": cfg.voice,
        "modelId": cfg.model,
        "samplingRate": PREVIEW_SAMPLE_RATE_HZ,
        "lang": _RIME_LANGUAGES.get(cfg.language, cfg.language),
        # Passed through unchanged, like the live call. Rime reads values
        # above 1 as slower speech.
        "speedAlpha": cfg.speed,
    }
    response = await post_for_audio(
        client,
        "Rime",
        TTS_ENDPOINT,
        json=payload,
        headers={"Authorization": f"Bearer {cfg.api_key}", "Accept": "audio/pcm"},
    )
    return pcm_to_wav(response.content, sample_rate=PREVIEW_SAMPLE_RATE_HZ)
