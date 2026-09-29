"""Build Pipecat services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_tts
from .catalog import DEFAULT_BASE_URL
from .config import KenpathLabsTTSConfig


@register_tts
def create_tts(cfg: KenpathLabsTTSConfig):
    from svara.pipecat import SvaraTTSService, SvaraTTSSettings

    return SvaraTTSService(
        api_key=cfg.api_key,
        base_url=cfg.base_url or DEFAULT_BASE_URL,
        settings=SvaraTTSSettings(
            voice=cfg.voice,
            model=cfg.model,
            language=cfg.language,
            speed=cfg.speed,
        ),
    )
