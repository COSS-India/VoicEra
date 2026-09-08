"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_stt, register_tts, api_key
from .config import DeepgramSTTConfig, DeepgramTTSConfig


@register_stt
def create_stt(cfg: DeepgramSTTConfig):
    from pipecat.services.deepgram.stt import DeepgramSTTService, DeepgramSTTSettings

    return DeepgramSTTService(
        api_key=api_key(cfg.api_key),
        settings=DeepgramSTTSettings(model=cfg.model, language=cfg.language),
    )


@register_tts
def create_tts(cfg: DeepgramTTSConfig):
    from pipecat.services.deepgram.tts import DeepgramTTSService, DeepgramTTSSettings

    return DeepgramTTSService(
        api_key=api_key(cfg.api_key),
        settings=DeepgramTTSSettings(voice=cfg.voice),
    )
