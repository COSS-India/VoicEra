"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_tts
from .config import RimeTTSConfig


@register_tts
def create_tts(cfg: RimeTTSConfig):
    from pipecat.services.rime.tts import RimeTTSService, RimeTTSSettings

    return RimeTTSService(
        api_key=cfg.api_key,
        settings=RimeTTSSettings(
            voice=cfg.voice,
            model=cfg.model,
            language=cfg.language,
            speedAlpha=cfg.speed,
        ),
    )

