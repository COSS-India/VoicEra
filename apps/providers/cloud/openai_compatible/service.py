"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from ...registry import register_llm, api_key, llm_settings
from .config import OpenAICompatibleLLMConfig
from .history import Messages, message_shaper


@lru_cache(maxsize=1)
def _shaping_service_class() -> type:
    """``OpenAILLMService`` that sends a shaped message list.

    ``build_chat_completion_params`` is the single point where a context turns
    into a request body — streaming completions and out-of-band inference both
    go through it — so overriding it covers every call the service makes.
    """
    from pipecat.services.openai.llm import OpenAILLMService

    class ShapedMessagesOpenAILLMService(OpenAILLMService):
        def __init__(
            self,
            *,
            shape_messages: Callable[[Messages], Messages],
            **kwargs: Any,
        ) -> None:
            super().__init__(**kwargs)
            self._shape_messages = shape_messages

        def build_chat_completion_params(
            self, params_from_context: Any
        ) -> dict[str, Any]:
            params = super().build_chat_completion_params(params_from_context)
            params["messages"] = self._shape_messages(params["messages"])
            return params

    return ShapedMessagesOpenAILLMService


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

    settings = llm_settings(cfg)
    if cfg.endpoint_send_caller_phone:
        # The endpoint keys its records on this number and rejects a request
        # without it, so a call with no number cannot usefully start.
        if not cfg.caller_phone:
            raise ValueError(
                "This provider connection sends the caller's phone number, "
                "but none is known for this call"
            )
        # ``extra`` is merged into every request body the service builds.
        settings["extra"] = {"metadata": {"caller_phone": cfg.caller_phone}}

    common = {
        "api_key": api_key(cfg.api_key),
        "base_url": cfg.base_url,
        "settings": OpenAILLMSettings(**settings),
    }

    shape_messages = message_shaper(
        history_mode=cfg.effective_history_mode,
        system_prompt_mode=cfg.effective_system_prompt_mode,
    )
    if shape_messages is None:
        # Nothing to trim — the stock service, exactly as before either setting
        # existed.
        return OpenAILLMService(**common)

    return _shaping_service_class()(shape_messages=shape_messages, **common)
