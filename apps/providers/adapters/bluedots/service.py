"""Build Pipecat services from BlueDots configs."""

from __future__ import annotations

from ...registry import api_key, llm_settings, register_llm
from .catalog import resolve_base_url
from .config import BlueDotsLLMConfig


@register_llm
def create_llm(cfg: BlueDotsLLMConfig):
    from pipecat.services.openai.base_llm import OpenAILLMSettings

    from .llm import BlueDotsLLMService

    base_url = resolve_base_url(cfg.base_url)
    if not base_url:
        raise ValueError("bluedots requires a base_url")

    settings = llm_settings(cfg)
    # Always attach caller phone — empty for web/unknown numbers so the request
    # still succeeds. ``extra`` is merged into every chat-completion body.
    settings["extra"] = {"metadata": {"caller_phone": cfg.caller_phone or ""}}

    return BlueDotsLLMService(
        api_key=api_key(cfg.api_key),
        base_url=base_url,
        settings=OpenAILLMSettings(**settings),
    )
