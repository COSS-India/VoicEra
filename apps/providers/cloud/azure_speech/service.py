"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_stt, register_tts
from .config import AzureSpeechSTTConfig, AzureSpeechTTSConfig


@register_stt
def create_stt(cfg: AzureSpeechSTTConfig):
    from pipecat.services.azure.stt import AzureSTTService, AzureSTTSettings

    return AzureSTTService(
        api_key=cfg.api_key,
        region=cfg.region,
        settings=AzureSTTSettings(language=cfg.language),
    )


@register_tts
def create_tts(cfg: AzureSpeechTTSConfig):
    from pipecat.services.azure.tts import AzureTTSService, AzureTTSSettings

    return AzureTTSService(
        api_key=cfg.api_key,
        region=cfg.region,
        settings=AzureTTSSettings(
            voice=cfg.voice,
            language=cfg.language,
            rate=str(cfg.speed),
        ),
    )

