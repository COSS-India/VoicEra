"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_llm, register_stt, register_tts, api_key, llm_settings
from .config import OpenAILLMConfig, OpenAISTTConfig, OpenAITTSConfig


@register_stt
def create_stt(cfg: OpenAISTTConfig):
    from pipecat.services.openai.stt import OpenAISTTService, OpenAISTTSettings

    return OpenAISTTService(
        api_key=api_key(cfg.api_key),
        settings=OpenAISTTSettings(model=cfg.model, language=cfg.language),
    )


@register_tts
def create_tts(cfg: OpenAITTSConfig):
    from pipecat.services.openai.tts import OpenAITTSService, OpenAITTSSettings

    return OpenAITTSService(
        api_key=api_key(cfg.api_key),
        settings=OpenAITTSSettings(model=cfg.model, voice=cfg.voice),
    )


@register_llm
def create_llm(cfg: OpenAILLMConfig):
    from pipecat.services.openai.base_llm import OpenAILLMSettings
    from pipecat.services.openai.llm import OpenAILLMService

    return OpenAILLMService(
        api_key=api_key(cfg.api_key),
        settings=OpenAILLMSettings(**llm_settings(cfg)),
    )
