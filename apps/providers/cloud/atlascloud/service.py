"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_llm, api_key, llm_settings
from .catalog import BASE_URL
from .config import AtlasCloudLLMConfig


@register_llm
def create_llm(cfg: AtlasCloudLLMConfig):
    from pipecat.services.openai.base_llm import OpenAILLMSettings
    from pipecat.services.openai.llm import OpenAILLMService

    return OpenAILLMService(
        api_key=api_key(cfg.api_key),
        settings=OpenAILLMSettings(**llm_settings(cfg)),
        base_url=BASE_URL,
    )

