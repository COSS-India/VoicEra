"""Direct (non-Pipecat) TTS preview for Sarvam Bulbul."""

from __future__ import annotations

import base64

import httpx

from ...capabilities import api_capabilities
from ...preview import PreviewProviderError, register_preview, resolve_preview_sample_rate
from .catalog import TTS_CAPABILITIES
from .config import SarvamTTSConfig

_ENDPOINT = "https://api.sarvam.ai/text-to-speech"


def _wire_language_code(model: str, canonical: str) -> str:
    """Map a canonical language id (e.g. ``hi``) to Sarvam's vendor code (``hi-IN``)."""
    languages = api_capabilities(TTS_CAPABILITIES).get(model, {}).get("languages", {})
    return languages.get(canonical, canonical)


@register_preview("sarvam")
async def synthesize(cfg: SarvamTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    payload = {
        "text": text,
        "target_language_code": _wire_language_code(cfg.model, cfg.language),
        "speaker": cfg.voice,
        "model": cfg.model,
        "pace": cfg.speed,
        "speech_sample_rate": resolve_preview_sample_rate(cfg),
        "output_audio_codec": "wav",
    }
    try:
        response = await client.post(
            _ENDPOINT,
            json=payload,
            headers={"api-subscription-key": cfg.api_key},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise PreviewProviderError(f"Sarvam preview failed: {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise PreviewProviderError(f"Sarvam preview request failed: {exc}") from exc

    data = response.json()
    audios = data.get("audios") or []
    if not audios:
        raise PreviewProviderError("Sarvam preview returned no audio")
    return base64.b64decode(audios[0])
