"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_llm, register_stt, register_tts, llm_settings
from .config import SarvamLLMConfig, SarvamSTTConfig, SarvamTTSConfig
from .catalog import DEFAULT_LLM_BASE_URL


@register_stt
def create_stt(cfg: SarvamSTTConfig):
    from pipecat.services.sarvam.stt import SarvamSTTService, SarvamSTTSettings

    return SarvamSTTService(
        api_key=cfg.api_key,
        settings=SarvamSTTSettings(model=cfg.model, language=cfg.language),
    )


@register_tts
def create_tts(cfg: SarvamTTSConfig):
    from pipecat.services.sarvam.tts import SarvamTTSService, SarvamTTSSettings

    return SarvamTTSService(
        api_key=cfg.api_key,
        settings=SarvamTTSSettings(
            model=cfg.model,
            voice=cfg.voice,
            language=cfg.language,
            pace=cfg.speed,
        ),
    )


@register_llm
def create_llm(cfg: SarvamLLMConfig):
    from pipecat.services.sarvam.llm import SarvamLLMService, SarvamLLMSettings

    return SarvamLLMService(
        api_key=cfg.api_key,
        base_url=DEFAULT_LLM_BASE_URL,
        settings=SarvamLLMSettings(**llm_settings(cfg))
    )

