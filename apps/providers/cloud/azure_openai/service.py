"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_llm, api_key, llm_settings
from .config import AzureOpenAILLMConfig


@register_llm
def create_llm(cfg: AzureOpenAILLMConfig):
    from pipecat.services.azure.llm import AzureLLMService, AzureLLMSettings

    return AzureLLMService(
        api_key=api_key(cfg.api_key),
        endpoint=cfg.endpoint,
        settings=AzureLLMSettings(**llm_settings(cfg)),
    )

