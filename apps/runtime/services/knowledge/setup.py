"""Wire knowledge-base modes into a Pipecat pipeline."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    LLMContextAggregatorPair,
)

from apps.runtime.services.knowledge.config import (
    KnowledgeRuntimeConfig,
    parse_knowledge_config,
)
from apps.runtime.services.knowledge.context_processor import KnowledgeContextProcessor
from apps.runtime.services.knowledge.tool import build_knowledge_tool


def configure_knowledge_base(
    agent: dict[str, Any],
    *,
    org_id: str,
    context: LLMContext,
    aggregators: LLMContextAggregatorPair,
) -> KnowledgeContextProcessor | None:
    """Apply tool or context KB mode to the pipeline context."""
    kb_config = parse_knowledge_config(agent)
    if kb_config is None:
        return None

    if kb_config.mode == "tool":
        tool_fn = build_knowledge_tool(
            org_id=org_id,
            document_ids=kb_config.document_ids,
            top_k=kb_config.top_k,
        )
        context.set_tools([tool_fn])
        logger.info(
            "Knowledge base tool mode enabled agent_id={} documents={}",
            agent.get("agent_id"),
            len(kb_config.document_ids),
        )
        return None

    processor = KnowledgeContextProcessor(
        org_id=org_id,
        document_ids=kb_config.document_ids,
        top_k=kb_config.top_k,
        context=context,
    )
    user_aggregator, assistant_aggregator = aggregators

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def _restore_kb_context(
        _aggregator: Any, message: AssistantTurnStoppedMessage
    ) -> None:
        if message.interrupted:
            return
        await processor.restore_user_message()

    logger.info(
        "Knowledge base context mode enabled agent_id={} documents={}",
        agent.get("agent_id"),
        len(kb_config.document_ids),
    )
    return processor
