"""Turn-stopped logging handlers for the Pipecat pipeline."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    UserTurnStoppedMessage,
)

from apps.runtime.services.privacy.redaction import redact_if_enabled


def register_turn_logging_handlers(
    user_aggregator: Any,
    assistant_aggregator: Any,
    *,
    session_label: str,
) -> None:
    @user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped(
        aggregator: Any, strategy: Any, message: UserTurnStoppedMessage
    ) -> None:
        logger.info("[{}] user: {}", message.timestamp, redact_if_enabled(message.content))

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn_stopped(
        aggregator: Any, message: AssistantTurnStoppedMessage
    ) -> None:
        if message.interrupted:
            logger.info("Assistant interrupted {}", session_label)
        if message.content:
            logger.info(
                "[{}] assistant: {}", message.timestamp, redact_if_enabled(message.content)
            )
