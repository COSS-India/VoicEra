"""Tests for switch_language tool registration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pipecat.adapters.schemas.direct_function import DirectFunctionWrapper
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.aggregators.llm_context import LLMContext, NOT_GIVEN
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams

from apps.runtime.services.language_switch.frames import LanguageSwitchFrame
from apps.runtime.services.language_switch.tools import configure_language_switching


def _switcher() -> MagicMock:
    switcher = MagicMock()
    switcher.apply_language = AsyncMock(return_value=True)
    switcher.services = []
    switcher.register_direct_function = MagicMock()
    return switcher


def _registered_handler(llm: MagicMock):
    assert llm.register_direct_function.called
    return llm.register_direct_function.call_args.args[0]


def test_tool_not_registered_for_single_language():
    context = LLMContext([])
    agent = {
        "config": {
            "language": {"primary": "hi", "secondary": []},
        }
    }
    configure_language_switching(
        agent,
        context=context,
        stt_switcher=_switcher(),
        tts_switcher=_switcher(),
        llm_switcher=_switcher(),
    )
    assert context.tools is NOT_GIVEN


def test_tool_registered_for_multi_language():
    context = LLMContext([])
    agent = {
        "config": {
            "language": {"primary": "hi", "secondary": ["mr"]},
        }
    }
    configure_language_switching(
        agent,
        context=context,
        stt_switcher=_switcher(),
        tts_switcher=_switcher(),
        llm_switcher=_switcher(),
    )
    assert isinstance(context.tools, ToolsSchema)
    assert len(context.tools.standard_tools) == 1
    assert context.tools.standard_tools[0].name == "switch_language"


@pytest.mark.asyncio
async def test_switch_language_queues_frame_downstream():
    context = LLMContext([])
    agent = {
        "config": {
            "language": {"primary": "hi", "secondary": ["mr"]},
        }
    }
    stt = _switcher()
    tts = _switcher()
    llm = _switcher()
    configure_language_switching(
        agent,
        context=context,
        stt_switcher=stt,
        tts_switcher=tts,
        llm_switcher=llm,
    )
    llm_service = MagicMock()
    llm_service.push_frame = AsyncMock()
    result_callback = AsyncMock()
    params = FunctionCallParams(
        function_name="switch_language",
        tool_call_id="1",
        arguments={"language": "mr"},
        llm=llm_service,
        context=context,
        result_callback=result_callback,
    )
    wrapper = DirectFunctionWrapper(_registered_handler(llm))
    await wrapper.invoke({"language": "mr"}, params)

    stt.apply_language.assert_not_awaited()
    tts.apply_language.assert_not_awaited()
    llm.apply_language.assert_not_awaited()
    llm_service.push_frame.assert_awaited_once()
    frame, direction = llm_service.push_frame.await_args.args
    assert isinstance(frame, LanguageSwitchFrame)
    assert frame.language == "mr"
    assert direction == FrameDirection.DOWNSTREAM
    result_callback.assert_awaited_once_with({"status": "ok", "language": "mr"})


@pytest.mark.asyncio
async def test_switch_language_rejects_unsupported():
    context = LLMContext([])
    agent = {
        "config": {
            "language": {"primary": "hi", "secondary": ["mr"]},
        }
    }
    stt = _switcher()
    llm = _switcher()
    configure_language_switching(
        agent,
        context=context,
        stt_switcher=stt,
        tts_switcher=_switcher(),
        llm_switcher=llm,
    )
    llm_service = MagicMock()
    llm_service.push_frame = AsyncMock()
    result_callback = AsyncMock()
    params = FunctionCallParams(
        function_name="switch_language",
        tool_call_id="1",
        arguments={"language": "kannada"},
        llm=llm_service,
        context=context,
        result_callback=result_callback,
    )
    wrapper = DirectFunctionWrapper(_registered_handler(llm))
    await wrapper.invoke({"language": "kannada"}, params)

    llm_service.push_frame.assert_not_awaited()
    result_callback.assert_awaited_once_with(
        {
            "status": "error",
            "reason": "unsupported_language",
            "language": "kannada",
            "allowed": ["hi", "mr"],
        }
    )
