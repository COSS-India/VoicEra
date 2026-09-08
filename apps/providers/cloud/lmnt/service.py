"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_tts
from .config import LmntTTSConfig


@register_tts
def create_tts(cfg: LmntTTSConfig):
    from pipecat.services.lmnt.tts import LmntTTSService, LmntTTSSettings

    return LmntTTSService(
        api_key=cfg.api_key,
        settings=LmntTTSSettings(
            voice=cfg.voice,
            language=cfg.language,
            model=cfg.model,
        ),
    )

