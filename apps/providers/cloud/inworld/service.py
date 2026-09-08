"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_tts
from .config import InworldTTSConfig


@register_tts
def create_tts(cfg: InworldTTSConfig):
    from pipecat.services.inworld.tts import InworldTTSService, InworldTTSSettings

    return InworldTTSService(
        api_key=cfg.api_key,
        settings=InworldTTSSettings(
            voice=cfg.voice,
            model=cfg.model,
            language=cfg.language,
            speaking_rate=cfg.speed,
            delivery_mode=cfg.delivery_mode,
        ),
    )

