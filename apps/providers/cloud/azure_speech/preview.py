"""Direct (non-Pipecat) TTS preview for Azure Speech."""

from __future__ import annotations

from xml.sax.saxutils import escape

import httpx

from ...preview import PreviewProviderError, post_for_audio, register_preview, resolve_wire_language
from .catalog import SPEECH_REGIONS, TTS_CAPABILITIES, TTS_ENDPOINT_TEMPLATE
from .config import AzureSpeechTTSConfig

# 16 kHz mono s16 inside a RIFF header, so the response is already WAV.
_OUTPUT_FORMAT = "riff-16khz-16bit-mono-pcm"
# Azure rejects requests without a User-Agent.
_USER_AGENT = "voicera-voice-preview"
_ATTR_ENTITIES = {"'": "&apos;", '"': "&quot;"}


def build_ssml(cfg: AzureSpeechTTSConfig, text: str) -> str:
    """Build the SSML the live-call service sends: voice, locale and ``rate`` prosody."""
    language = escape(resolve_wire_language(TTS_CAPABILITIES, cfg.model, cfg.language), _ATTR_ENTITIES)
    voice = escape(cfg.voice, _ATTR_ENTITIES)
    return (
        f"<speak version='1.0' xml:lang='{language}' xmlns='http://www.w3.org/2001/10/synthesis'>"
        f"<voice name='{voice}'><prosody rate='{cfg.speed}'>{escape(text)}</prosody></voice></speak>"
    )


@register_preview("azure_speech")
async def synthesize(cfg: AzureSpeechTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text``; raise :class:`PreviewProviderError` on any vendor failure."""
    # The region becomes the URL host, so only known Azure regions are allowed.
    # Hostnames ignore case, so "EastUS" works on a live call and must here too.
    region = cfg.region.strip().lower()
    if region not in SPEECH_REGIONS:
        raise PreviewProviderError("Azure Speech preview: unknown region")
    response = await post_for_audio(
        client,
        "Azure Speech",
        TTS_ENDPOINT_TEMPLATE.format(region=region),
        content=build_ssml(cfg, text).encode(),
        headers={
            "Ocp-Apim-Subscription-Key": cfg.api_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": _OUTPUT_FORMAT,
            "User-Agent": _USER_AGENT,
        },
    )
    return response.content
