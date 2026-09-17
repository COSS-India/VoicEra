"""LLM tool for mid-call language switching."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.aggregators.llm_context import LLMContext, NOT_GIVEN
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams

from apps.runtime.services.language_switch.frames import LanguageSwitchFrame
from apps.runtime.services.language_switch.pool import configured_languages
from apps.runtime.services.language_switch.switcher import ModelServiceSwitcher


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


def configure_language_switching(
    agent: dict[str, Any],
    *,
    context: LLMContext,
    stt_switcher: ModelServiceSwitcher,
    tts_switcher: ModelServiceSwitcher,
    llm_switcher: ModelServiceSwitcher,
    agent_id: str | None = None,
) -> None:
    """Register ``switch_language`` when the agent has multiple languages."""
    languages = configured_languages(agent)
    if len(languages) <= 1:
        return

    switchers = (stt_switcher, tts_switcher, llm_switcher)
    lang_list = ", ".join(languages)

    async def switch_language(params: FunctionCallParams, language: str) -> None:
        """Switch STT, TTS, and LLM to another configured language."""

        lang = (language or "").strip()
        frame = LanguageSwitchFrame(language=lang)

        for switcher in switchers:
            await switcher.apply_language(lang)

        logger.info("Switching language to {}", lang)
        await params.llm.push_frame(frame, FrameDirection.DOWNSTREAM)
        await params.llm.push_frame(frame, FrameDirection.UPSTREAM)
        await params.result_callback({"status": "ok", "language": lang})

    switch_language.__doc__ = (
        "Switch the conversation to another configured language. "
        f"Use when the user clearly wants to speak in a different language. "
        f"Allowed values: {lang_list}."
        f"if the users asks to speak in kannada, the lang is kn"
    )

    _append_tools(context, [switch_language])
    logger.info(
        "Language switching enabled agent_id={} languages={}",
        agent_id,
        languages,
    )
