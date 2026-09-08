"""Unit tests for graceful LLM call ending."""

from __future__ import annotations

from pipecat.processors.aggregators.llm_context import LLMContext, NOT_GIVEN

from apps.runtime.services.pipecat.call_ending import configure_call_ending, end_conversation


async def _kb_tool(params, query: str) -> None:
    """Search attached knowledge-base documents for relevant information.

    Args:
        query: Natural-language search query.
    """
    await params.result_callback({"query": query})


def test_configure_call_ending_disabled() -> None:
    context = LLMContext([])
    configure_call_ending({}, context=context)
    assert context.tools is NOT_GIVEN


def test_configure_call_ending_registers_tool() -> None:
    context = LLMContext([])
    configure_call_ending(
        {
            "automatic_call_ending": {
                "enabled": True,
                "graceful_llm_call_ending": True,
            }
        },
        context=context,
    )

    names = {tool.name for tool in context.tools.standard_tools}
    assert names == {"end_conversation"}


def test_configure_call_ending_appends_to_existing_tools() -> None:
    context = LLMContext([])
    context.set_tools([_kb_tool])
    configure_call_ending(
        {
            "automatic_call_ending": {
                "enabled": True,
                "graceful_llm_call_ending": True,
            }
        },
        context=context,
    )

    names = {tool.name for tool in context.tools.standard_tools}
    assert names == {"_kb_tool", "end_conversation"}


def test_configure_call_ending_skips_duplicate() -> None:
    context = LLMContext([])
    context.set_tools([end_conversation])
    configure_call_ending(
        {
            "automatic_call_ending": {
                "enabled": True,
                "graceful_llm_call_ending": True,
            }
        },
        context=context,
    )

    assert len(context.tools.standard_tools) == 1
