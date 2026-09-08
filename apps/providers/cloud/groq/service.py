"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_llm, api_key, llm_settings
from .config import GroqLLMConfig


@register_llm
def create_llm(cfg: GroqLLMConfig):
    from pipecat.services.groq.llm import GroqLLMService, GroqLLMSettings

    return GroqLLMService(
        api_key=api_key(cfg.api_key),
        settings=GroqLLMSettings(**llm_settings(cfg)),
    )

