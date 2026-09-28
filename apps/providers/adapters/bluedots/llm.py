"""BlueDots Pipecat LLM — OpenAILLMService with current-turn message shaping.

Subclassing ``OpenAILLMService`` keeps stock Pipecat frames and metrics
(``LLMFullResponseStart/EndFrame``, TTFB / processing / usage MetricsFrames,
``LLMTextFrame``, tool-call frames). Only ``build_chat_completion_params`` is
overridden so the wire body is trimmed to the current turn.
"""

from __future__ import annotations

from typing import Any

from pipecat.services.openai.llm import OpenAILLMService

from .history import Messages, trim_to_current_turn


class BlueDotsLLMService(OpenAILLMService):
    """OpenAI-compatible LLM that always sends the current turn only."""

    def build_chat_completion_params(
        self, params_from_context: Any
    ) -> dict[str, Any]:
        params = super().build_chat_completion_params(params_from_context)
        messages: Messages = list(params.get("messages") or [])
        params["messages"] = trim_to_current_turn(messages)
        return params
