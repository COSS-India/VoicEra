"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_stt, register_tts
from .config import SmallestSTTConfig, SmallestTTSConfig


@register_stt
def create_stt(cfg: SmallestSTTConfig):
    from pipecat.services.smallest.stt import SmallestSTTService, SmallestSTTSettings

    return SmallestSTTService(
        api_key=cfg.api_key,
        settings=SmallestSTTSettings(language=cfg.language),
    )


@register_tts
def create_tts(cfg: SmallestTTSConfig):
    from pipecat.services.smallest.tts import SmallestTTSService, SmallestTTSSettings

    return SmallestTTSService(
        api_key=cfg.api_key,
        sample_rate=cfg.sample_rate,
        settings=SmallestTTSSettings(
            model=cfg.model,
            voice=cfg.voice,
            language=cfg.language,
            speed=cfg.speed,
        ),
    )

