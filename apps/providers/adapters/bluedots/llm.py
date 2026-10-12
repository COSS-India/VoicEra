"""BlueDots Pipecat LLM — OpenAILLMService with current-turn message shaping.

Subclassing ``OpenAILLMService`` keeps stock Pipecat frames and metrics
(``LLMFullResponseStart/EndFrame``, TTFB / processing / usage MetricsFrames,
``LLMTextFrame``, tool-call frames). ``build_chat_completion_params`` is
overridden so the wire body is trimmed to the current turn, and
``set_call_id`` (the same hook ``run_pipeline`` already calls on every
provider that exposes it, today only Kenpath / Kenpath DLS — see
``docs/developer/services/providers.md``) adds VoicEra's own call id to the
``metadata`` object alongside ``caller_phone`` so BlueDots' Agent Core can
key a session per call rather than per phone number.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
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

    def set_call_id(self, call_id: str | None) -> None:
        """Add VoicEra's call id to every outgoing ``metadata`` object.

        Additive only: ``caller_phone`` (set at construction in
        ``service.create_llm``) is untouched, and a call with no id yet
        (``set_call_id`` never invoked, e.g. in the adapter's own unit
        tests that call ``build_chat_completion_params`` directly) keeps
        sending exactly what it sends today.
        """
        call_id = (call_id or "").strip() or None
        metadata = self._settings.extra.setdefault("metadata", {})
        metadata["call_id"] = call_id or ""
        if call_id:
            logger.info("BlueDots metadata.call_id set to {}", call_id)
