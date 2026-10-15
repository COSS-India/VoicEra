"""Build Pipecat STT and TTS services from Raya configs."""

from __future__ import annotations

from ...registry import register_stt, register_tts
from .catalog import resolve_wire_language
from .config import RayaSTTConfig, RayaTTSConfig


@register_stt
def create_stt(cfg: RayaSTTConfig):
    from .stt import RayaSTTService

    language = resolve_wire_language(cfg.model, cfg.language, kind="stt")
    return RayaSTTService(
        api_key=cfg.api_key,
        language=language,
    )


@register_tts
def create_tts(cfg: RayaTTSConfig):
    from .tts import RayaTTSService

    language = resolve_wire_language(cfg.model, cfg.language, kind="tts")
    return RayaTTSService(
        api_key=cfg.api_key,
        voice=cfg.voice,
        model=cfg.model,
        language=language,
        speed=cfg.speed,
        sample_rate=cfg.sample_rate,
        base_url=cfg.base_url,
    )
