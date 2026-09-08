"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_tts, api_key
from .config import XAITTSConfig


@register_tts
def create_tts(cfg: XAITTSConfig):
    try:
        from pipecat.services.xai.tts import XAITTSService, XAIWebsocketTTSSettings

        return XAITTSService(
            api_key=api_key(cfg.api_key),
            settings=XAIWebsocketTTSSettings(
                voice=cfg.voice,
                language=cfg.language,
            ),
        )
    except ImportError:
        from pipecat.services.xai.tts import XAIHttpTTSService, XAITTSSettings

        return XAIHttpTTSService(
            api_key=api_key(cfg.api_key),
            settings=XAITTSSettings(voice=cfg.voice, language=cfg.language),
        )

