"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_stt, register_tts
from .catalog import DEFAULT_BASE_URL
from .config import ElevenLabsSTTConfig, ElevenLabsTTSConfig


def _stt_base_url(url: str) -> str:
    """Pipecat realtime STT expects a host (no scheme)."""
    return (
        url.removeprefix("https://")
        .removeprefix("http://")
        .removeprefix("wss://")
        .removeprefix("ws://")
        .rstrip("/")
    )


def _tts_ws_url(url: str) -> str:
    """Pipecat WebSocket TTS expects a wss:// base URL."""
    if url.startswith("wss://") or url.startswith("ws://"):
        return url.rstrip("/")
    if url.startswith("https://"):
        return "wss://" + url.removeprefix("https://").rstrip("/")
    if url.startswith("http://"):
        return "ws://" + url.removeprefix("http://").rstrip("/")
    return f"wss://{url.rstrip('/')}"


@register_stt
def create_stt(cfg: ElevenLabsSTTConfig):
    from pipecat.services.elevenlabs.stt import (
        ElevenLabsRealtimeSTTService,
        ElevenLabsRealtimeSTTSettings,
    )

    return ElevenLabsRealtimeSTTService(
        api_key=cfg.api_key,
        base_url=_stt_base_url(DEFAULT_BASE_URL),
        settings=ElevenLabsRealtimeSTTSettings(
            model=cfg.model,
            language=cfg.language,
        ),
    )


@register_tts
def create_tts(cfg: ElevenLabsTTSConfig):
    from pipecat.services.elevenlabs.tts import (
        ElevenLabsTTSService,
        ElevenLabsTTSSettings,
    )

    return ElevenLabsTTSService(
        api_key=cfg.api_key,
        url=_tts_ws_url(DEFAULT_BASE_URL),
        settings=ElevenLabsTTSSettings(
            voice=cfg.voice,
            model=cfg.model,
            language=cfg.language,
            speed=cfg.speed,
        ),
    )
