"""Graceful LLM call ending via Pipecat function calling."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import EndWorkerFrame
from pipecat.processors.aggregators.llm_context import LLMContext, NOT_GIVEN
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams


async def end_conversation(params: FunctionCallParams) -> None:
    """End the conversation and shut down the bot.

    Call this when the user says goodbye or the task is complete.
    """
    await params.result_callback({"status": "ended"})
    await params.llm.push_frame(EndWorkerFrame(), FrameDirection.DOWNSTREAM)


def _call_ending_enabled(behaviour: dict[str, Any]) -> bool:
    ending = behaviour.get("automatic_call_ending") or {}
    return bool(ending.get("enabled") and ending.get("graceful_llm_call_ending"))


def _append_tools(context: LLMContext, tools: list[Any]) -> None:
    existing = context.tools
    if existing is NOT_GIVEN:
        context.set_tools(tools)
        return

    if not isinstance(existing, ToolsSchema):
        context.set_tools(tools)
        return

    names = {tool.name for tool in existing.standard_tools}
    merged = list(existing.standard_tools)
    for tool in tools:
        name = tool.name if isinstance(tool, FunctionSchema) else tool.__name__
        if name in names:
            continue
        merged.append(tool)
        names.add(name)

    context.set_tools(merged)


def configure_call_ending(
    behaviour: dict[str, Any],
    *,
    context: LLMContext,
    agent_id: str | None = None,
) -> None:
    """Register end_conversation on the LLM context when call ending is enabled."""
    if not _call_ending_enabled(behaviour):
        return

    _append_tools(context, [end_conversation])
    logger.info("Graceful LLM call ending enabled agent_id={}", agent_id)
