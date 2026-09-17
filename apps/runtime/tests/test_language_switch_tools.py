"""Tests for switch_language tool registration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
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
    return switcher


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
async def test_switch_language_applies_all_switchers():
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
    llm_member = MagicMock()
    llm_member.push_frame = AsyncMock()
    result_callback = AsyncMock()
    params = FunctionCallParams(
        function_name="switch_language",
        tool_call_id="1",
        arguments={"language": "mr"},
        llm=llm_member,
        pipeline_worker=MagicMock(),
        context=context,
        result_callback=result_callback,
    )
    wrapper = context.tools.direct_functions[0]
    await wrapper.invoke({"language": "mr"}, params)

    stt.apply_language.assert_awaited_once_with("mr")
    tts.apply_language.assert_awaited_once_with("mr")
    llm.apply_language.assert_awaited_once_with("mr")
    assert llm_member.push_frame.await_count == 2
    directions = {call.args[1] for call in llm_member.push_frame.await_args_list}
    assert directions == {FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM}
    frame_types = {type(call.args[0]) for call in llm_member.push_frame.await_args_list}
    assert frame_types == {LanguageSwitchFrame}
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
    tts = _switcher()
    llm = _switcher()
    configure_language_switching(
        agent,
        context=context,
        stt_switcher=stt,
        tts_switcher=tts,
        llm_switcher=llm,
    )
    result_callback = AsyncMock()
    params = FunctionCallParams(
        function_name="switch_language",
        tool_call_id="1",
        arguments={"language": "kannada"},
        llm=MagicMock(push_frame=AsyncMock()),
        pipeline_worker=MagicMock(),
        context=context,
        result_callback=result_callback,
    )
    wrapper = context.tools.direct_functions[0]
    await wrapper.invoke({"language": "kannada"}, params)

    stt.apply_language.assert_not_awaited()
    result_callback.assert_awaited_once_with(
        {
            "status": "error",
            "reason": "unsupported_language",
            "language": "kannada",
            "allowed": ["hi", "mr"],
        }
    )
