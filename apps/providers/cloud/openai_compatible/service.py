"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_llm, api_key, llm_settings
from .config import OpenAICompatibleLLMConfig


@register_llm
def create_llm(cfg: OpenAICompatibleLLMConfig):
    from pipecat.services.openai.base_llm import OpenAILLMSettings
    from pipecat.services.openai.llm import OpenAILLMService

    if not cfg.base_url:
        raise ValueError(
            "openai_compatible requires base_url — the runtime merges it in "
            "from the agent's provider connection"
        )
    if not cfg.model:
        raise ValueError("openai_compatible requires a model id")

    return OpenAILLMService(
        api_key=api_key(cfg.api_key),
        base_url=cfg.base_url,
        settings=OpenAILLMSettings(**llm_settings(cfg)),
    )
