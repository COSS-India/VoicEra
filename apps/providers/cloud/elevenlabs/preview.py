"""Direct (non-Pipecat) TTS preview for ElevenLabs."""

from __future__ import annotations

import httpx

from ...preview import (
    PREVIEW_SAMPLE_RATE_HZ,
    PreviewProviderError,
    pcm_to_wav,
    post_for_audio,
    register_preview,
    resolve_wire_language,
)
from .catalog import DEFAULT_BASE_URL, TTS_CAPABILITIES
from .config import ElevenLabsTTSConfig

# ElevenLabs rejects ``language_code`` on any other model (pipecat applies the same rule).
_LANGUAGE_CODE_MODELS = frozenset({"eleven_flash_v2_5", "eleven_turbo_v2_5"})


@register_preview("elevenlabs")
async def synthesize(cfg: ElevenLabsTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text``; raise :class:`PreviewProviderError` on any vendor failure."""
    # The voice id is user input and goes in the URL path: allow only plain ids.
    if not (cfg.voice.isascii() and cfg.voice.isalnum()):
        raise PreviewProviderError("ElevenLabs preview: voice id must be alphanumeric")
    payload: dict = {"text": text, "model_id": cfg.model, "voice_settings": {"speed": cfg.speed}}
    if cfg.model in _LANGUAGE_CODE_MODELS:
        payload["language_code"] = resolve_wire_language(TTS_CAPABILITIES, cfg.model, cfg.language)
    response = await post_for_audio(
        client,
        "ElevenLabs",
        f"{DEFAULT_BASE_URL}/v1/text-to-speech/{cfg.voice}",
        params={"output_format": f"pcm_{PREVIEW_SAMPLE_RATE_HZ}"},
        json=payload,
        headers={"xi-api-key": cfg.api_key},
    )
    return pcm_to_wav(response.content, sample_rate=PREVIEW_SAMPLE_RATE_HZ)
