"""Direct (non-Pipecat) TTS preview for Camb.ai MARS."""

from __future__ import annotations

import re

import httpx

from ...preview import PreviewProviderError, pcm_to_wav, post_for_audio, register_preview, resolve_wire_language
from .catalog import TTS_CAPABILITIES, TTS_ENDPOINT, TTS_SAMPLE_RATES
from .config import CambTTSConfig

_INSTRUCT_MODEL = "mars-instruct"
# ASCII digits only (str.isdigit also accepts "²", which int() rejects), bounded
# so the id fits a signed 64-bit integer and int() can never hit its digit limit.
_VOICE_ID_PATTERN = re.compile(r"[0-9]{1,18}")


@register_preview("camb")
async def synthesize(cfg: CambTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text``; raise :class:`PreviewProviderError` on any vendor failure."""
    sample_rate = TTS_SAMPLE_RATES.get(cfg.model)
    if sample_rate is None or not _VOICE_ID_PATTERN.fullmatch(cfg.voice):
        raise PreviewProviderError("Camb.ai preview: unknown model or non-numeric voice id")
    payload: dict = {
        "text": text,
        "voice_id": int(cfg.voice),
        "language": resolve_wire_language(TTS_CAPABILITIES, cfg.model, cfg.language),
        "speech_model": cfg.model,
        "output_configuration": {"format": "pcm_s16le"},
    }
    if cfg.model == _INSTRUCT_MODEL and cfg.user_instructions:
        payload["user_instructions"] = cfg.user_instructions
    response = await post_for_audio(client, "Camb.ai", TTS_ENDPOINT, json=payload, headers={"x-api-key": cfg.api_key})
    return pcm_to_wav(response.content, sample_rate=sample_rate)
