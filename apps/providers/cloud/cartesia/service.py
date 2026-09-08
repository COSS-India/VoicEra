"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_stt, register_tts
from .config import CartesiaSTTConfig, CartesiaTTSConfig


@register_stt
def create_stt(cfg: CartesiaSTTConfig):
    from pipecat.services.cartesia.stt import CartesiaSTTService, CartesiaSTTSettings

    return CartesiaSTTService(
        api_key=cfg.api_key,
        settings=CartesiaSTTSettings(model=cfg.model, language=cfg.language),
    )


@register_tts
def create_tts(cfg: CartesiaTTSConfig):
    from pipecat.services.cartesia.tts import (
        CartesiaTTSService,
        CartesiaTTSSettings,
        GenerationConfig,
    )

    return CartesiaTTSService(
        api_key=cfg.api_key,
        settings=CartesiaTTSSettings(
            voice=cfg.voice,
            model=cfg.model,
            language=cfg.language,
            generation_config=GenerationConfig(
                speed=cfg.speed,
                volume=cfg.volume,
            ),
        ),
    )

