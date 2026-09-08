"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_llm, register_stt, register_tts, api_key, llm_settings
from .catalog import DEFAULT_STT_LOCATION
from .config import GoogleLLMConfig, GoogleSTTConfig, GoogleTTSConfig


@register_stt
def create_stt(cfg: GoogleSTTConfig):
    from pipecat.services.google.stt import GoogleSTTService, GoogleSTTSettings

    return GoogleSTTService(
        credentials=cfg.credentials,
        location=DEFAULT_STT_LOCATION,
        settings=GoogleSTTSettings(model=cfg.model, language_codes=[cfg.language]),
    )


@register_tts
def create_tts(cfg: GoogleTTSConfig):
    from pipecat.services.google.tts import GoogleTTSService, GoogleTTSSettings

    return GoogleTTSService(
        credentials=cfg.credentials,
        settings=GoogleTTSSettings(
            model=cfg.model,
            voice=cfg.voice,
            language=cfg.language,
            speaking_rate=cfg.speed,
        ),
    )


@register_llm
def create_llm(cfg: GoogleLLMConfig):
    from pipecat.services.google.llm import GoogleLLMService, GoogleLLMSettings

    return GoogleLLMService(
        api_key=api_key(cfg.api_key),
        settings=GoogleLLMSettings(**llm_settings(cfg)),
    )
