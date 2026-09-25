"""Tests for ModelServiceSwitcher / ModelLLMSwitcher language routing."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMUpdateSettingsFrame,
    STTUpdateSettingsFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.settings import LLMSettings, STTSettings, TTSSettings

from apps.runtime.services.language_switch.frames import LanguageSwitchFrame
from apps.runtime.services.language_switch.routes import LanguageRoute
from apps.runtime.services.language_switch.switcher import (
    ModelLLMSwitcher,
    ModelServiceSwitcher,
)


class RecordingService(FrameProcessor):
    def __init__(self, name: str) -> None:
        super().__init__(name=name)
        self.applied: list[Any] = []
        self.synced_tools: list[Any] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, (STTUpdateSettingsFrame, TTSUpdateSettingsFrame, LLMUpdateSettingsFrame)):
            if frame.service is None or frame.service is self:
                self.applied.append(frame)
        await self.push_frame(frame, direction)

    def _sync_registered_tool_handlers(self, tools: Any) -> None:
        self.synced_tools.append(tools)


class TestModelServiceSwitcher(unittest.IsolatedAsyncioTestCase):
    async def test_settings_only_switch(self) -> None:
        service = RecordingService("tts-one")
        routes = {
            "hi": LanguageRoute(service=service, settings_delta=TTSSettings(language="hi")),
            "mr": LanguageRoute(service=service, settings_delta=TTSSettings(language="mr")),
        }
        switcher = ModelServiceSwitcher(
            kind="tts",
            services=[service],
            routes=routes,
            primary_language="hi",
        )

        applied = await switcher.apply_language("mr")
        self.assertTrue(applied)
        self.assertEqual(switcher.active_language, "mr")
        self.assertEqual(len(service.applied), 1)
        self.assertEqual(service.applied[0].delta.language, "mr")

    async def test_provider_switch_and_settings(self) -> None:
        stt_a = RecordingService("stt-a")
        stt_b = RecordingService("stt-b")
        routes = {
            "hi": LanguageRoute(service=stt_a, settings_delta=STTSettings(language="hi")),
            "kn": LanguageRoute(service=stt_b, settings_delta=STTSettings(language="kn")),
        }
        switcher = ModelServiceSwitcher(
            kind="stt",
            services=[stt_a, stt_b],
            routes=routes,
            primary_language="hi",
        )

        applied = await switcher.apply_language("kn")
        self.assertTrue(applied)
        self.assertIs(switcher.strategy.active_service, stt_b)
        self.assertEqual(len(stt_b.applied), 1)

    async def test_unknown_language_noop(self) -> None:
        service = RecordingService("stt-one")
        switcher = ModelServiceSwitcher(
            kind="stt",
            services=[service],
            routes={"hi": LanguageRoute(service=service, settings_delta=STTSettings(language="hi"))},
            primary_language="hi",
        )
        applied = await switcher.apply_language("xx")
        self.assertFalse(applied)
        self.assertEqual(switcher.active_language, "hi")
        self.assertEqual(service.applied, [])

    async def test_already_active_returns_true(self) -> None:
        service = RecordingService("stt-one")
        switcher = ModelServiceSwitcher(
            kind="stt",
            services=[service],
            routes={"hi": LanguageRoute(service=service, settings_delta=STTSettings(language="hi"))},
            primary_language="hi",
        )
        applied = await switcher.apply_language("hi")
        self.assertTrue(applied)
        self.assertEqual(service.applied, [])


class TestModelLLMSwitcher(unittest.IsolatedAsyncioTestCase):
    async def test_language_switch_frame_triggers_apply(self) -> None:
        service = RecordingService("llm-one")
        routes = {
            "hi": LanguageRoute(service=service, settings_delta=LLMSettings(model="gpt-4.1")),
            "mr": LanguageRoute(service=service, settings_delta=LLMSettings(model="gpt-4.1")),
        }
        switcher = ModelLLMSwitcher(
            services=[service],
            routes=routes,
            primary_language="hi",
        )

        await switcher.process_frame(LanguageSwitchFrame(language="mr"), FrameDirection.DOWNSTREAM)

        self.assertEqual(switcher.active_language, "mr")
        self.assertEqual(len(service.applied), 1)

    async def test_context_frame_syncs_tools_on_all_members(self) -> None:
        llm_a = RecordingService("llm-a")
        llm_b = RecordingService("llm-b")
        routes = {
            "hi": LanguageRoute(service=llm_a, settings_delta=LLMSettings(model="gpt-4.1")),
            "ta": LanguageRoute(service=llm_b, settings_delta=LLMSettings(model="claude")),
        }
        switcher = ModelLLMSwitcher(
            services=[llm_a, llm_b],
            routes=routes,
            primary_language="hi",
        )
        context = LLMContext([])
        tools = MagicMock(name="tools")
        context.set_tools = MagicMock()
        # Build a frame with tools on context
        context_frame = LLMContextFrame(context=context)
        # Patch tools property via assigning after construction is hard; use
        # switcher's sync path with bind_context instead for the main guarantee.
        switcher.bind_context(context)
        self.assertEqual(len(llm_a.synced_tools), 1)
        self.assertEqual(len(llm_b.synced_tools), 1)

        # Language switch to second LLM re-syncs tools
        await switcher.apply_language("ta")
        self.assertIs(switcher.strategy.active_service, llm_b)
        self.assertEqual(len(llm_a.synced_tools), 2)
        self.assertEqual(len(llm_b.synced_tools), 2)

    async def test_llm_context_frame_syncs_via_llm_switcher(self) -> None:
        llm_a = RecordingService("llm-a")
        llm_b = RecordingService("llm-b")
        switcher = ModelLLMSwitcher(
            services=[llm_a, llm_b],
            routes={
                "hi": LanguageRoute(service=llm_a, settings_delta=LLMSettings(model="a")),
                "ta": LanguageRoute(service=llm_b, settings_delta=LLMSettings(model="b")),
            },
            primary_language="hi",
        )
        context = LLMContext([])
        await switcher.process_frame(LLMContextFrame(context=context), FrameDirection.DOWNSTREAM)
        self.assertEqual(len(llm_a.synced_tools), 1)
        self.assertEqual(len(llm_b.synced_tools), 1)
