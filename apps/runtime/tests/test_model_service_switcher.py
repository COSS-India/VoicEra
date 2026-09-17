"""Tests for ModelServiceSwitcher language routing."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock

from pipecat.frames.frames import (
    Frame,
    LLMUpdateSettingsFrame,
    STTUpdateSettingsFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.settings import LLMSettings, STTSettings, TTSSettings

from apps.runtime.services.language_switch.frames import LanguageSwitchFrame
from apps.runtime.services.language_switch.routes import LanguageRoute
from apps.runtime.services.language_switch.switcher import ModelServiceSwitcher


class RecordingService(FrameProcessor):
    def __init__(self, name: str) -> None:
        super().__init__(name=name)
        self.applied: list[Any] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, (STTUpdateSettingsFrame, TTSUpdateSettingsFrame, LLMUpdateSettingsFrame)):
            if frame.service is None or frame.service is self:
                self.applied.append(frame)
        await self.push_frame(frame, direction)


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

    async def test_language_switch_frame_triggers_apply(self) -> None:
        service = RecordingService("llm-one")
        routes = {
            "hi": LanguageRoute(service=service, settings_delta=LLMSettings(model="gpt-4.1")),
            "mr": LanguageRoute(service=service, settings_delta=LLMSettings(model="gpt-4.1")),
        }
        switcher = ModelServiceSwitcher(
            kind="llm",
            services=[service],
            routes=routes,
            primary_language="hi",
        )

        await switcher.process_frame(LanguageSwitchFrame(language="mr"), FrameDirection.DOWNSTREAM)

        self.assertEqual(switcher.active_language, "mr")
        self.assertEqual(len(service.applied), 1)
