"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_llm, api_key, llm_settings
from .config import OpenRouterLLMConfig


@register_llm
def create_llm(cfg: OpenRouterLLMConfig):
    from pipecat.services.openrouter.llm import (
        OpenRouterLLMService,
        OpenRouterLLMSettings,
    )

    return OpenRouterLLMService(
        api_key=api_key(cfg.api_key),
        settings=OpenRouterLLMSettings(**llm_settings(cfg)),
    )

