"""LLM tool for mid-call language switching."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.adapters.schemas.direct_function import DirectFunctionWrapper
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.aggregators.llm_context import LLMContext, NOT_GIVEN
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams

from apps.providers.languages import label
from apps.runtime.services.language_switch.frames import LanguageSwitchFrame
from apps.runtime.services.language_switch.pool import configured_languages
from apps.runtime.services.language_switch.switcher import (
    ModelLLMSwitcher,
    ModelServiceSwitcher,
)


def _tool_schemas(tools: list[Any]) -> list[FunctionSchema]:
    schemas: list[FunctionSchema] = []
    for tool in tools:
        if isinstance(tool, FunctionSchema):
            schemas.append(tool)
        else:
            schemas.append(DirectFunctionWrapper(tool).to_function_schema())
    return schemas


def _append_tools(context: LLMContext, tools: list[Any]) -> None:
    incoming = _tool_schemas(tools)
    existing = context.tools
    if existing is NOT_GIVEN or not isinstance(existing, ToolsSchema):
        context.set_tools(ToolsSchema(standard_tools=incoming))
        return

    names = {tool.name for tool in existing.standard_tools}
    merged = list(existing.standard_tools)
    for schema in incoming:
        if schema.name in names:
            continue
        merged.append(schema)
        names.add(schema.name)

    context.set_tools(ToolsSchema(standard_tools=merged))


def configure_language_switching(
    agent: dict[str, Any],
    *,
    context: LLMContext,
    stt_switcher: ModelServiceSwitcher,
    tts_switcher: ModelServiceSwitcher,
    llm_switcher: ModelLLMSwitcher | ModelServiceSwitcher,
    agent_id: str | None = None,
) -> None:
    """Register ``switch_language`` when the agent has multiple languages.

    The tool only emits a ``LanguageSwitchFrame`` into the pipeline. Each
    switcher applies the switch when it sees that frame.
    """
    del stt_switcher, tts_switcher  # kept in signature for call-site uniformity
    languages = configured_languages(agent)
    if len(languages) <= 1:
        return

    allowed = set(languages)
    lang_list = ", ".join(f"{code} - {label(code)}" for code in languages)
    logger.info("Allowed languages: {}", lang_list)

    async def switch_language(params: FunctionCallParams, language: str) -> None:
        """Switch STT, TTS, and LLM to another configured language.

        Args:
            language: Language id to switch to (e.g. hi, kn).
        """
        lang = (language or "").strip()
        if lang not in allowed:
            await params.result_callback(
                {
                    "status": "error",
                    "reason": "unsupported_language",
                    "language": lang,
                    "allowed": languages,
                }
            )
            return

        frame = LanguageSwitchFrame(language=lang)
        await params.llm.push_frame(frame, FrameDirection.DOWNSTREAM)
        logger.info("Queued language switch to {}", lang)
        await params.result_callback({"status": "ok", "language": lang})

    switch_language.__doc__ = (
        "Switch the conversation to another configured language. "
        "Call this when the user clearly wants to speak in a different language. "
        f"Pass the language id exactly — allowed values: {lang_list}.\n\n"
        "Args:\n"
        "    language: Language id to switch to."
    )

    _append_tools(context, [switch_language])

    if isinstance(llm_switcher, ModelLLMSwitcher):
        llm_switcher.bind_context(context)
    register = getattr(llm_switcher, "register_direct_function", None)
    if callable(register):
        register(switch_language)

    logger.info(
        "Language switching enabled agent_id={} languages={}",
        agent_id,
        languages,
    )
