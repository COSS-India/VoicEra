"""The handoff message must be synthesised in the language it was queued for.

Production shape: the TTS switcher's Hindi and Kannada routes are the *same*
Raya service instance, so a language switch is a settings change on that
instance. The Raya adapter reads its voice and language when it starts a
message, so a settings change applied before the handoff is synthesised makes
the Hindi text come out in the Kannada voice (seen in the logs of a live call).

These tests use a fake TTS that behaves the same way and run through the real
``ModelServiceSwitcher`` on pipecat 0.0.108 and 1.8.1.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from pipecat.frames.frames import (
    Frame,
    TextFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.settings import TTSSettings
from pipecat.tests.utils import run_test

from apps.runtime.services.language_switch.frames import LanguageSwitchFrame
from apps.runtime.services.language_switch.routes import LanguageRoute
from apps.runtime.services.language_switch import switcher as switcher_module
from apps.runtime.services.language_switch.switcher import ModelServiceSwitcher


class VoiceTTS(FrameProcessor):
    """Synthesises like the Raya adapter: voice/language are read when a message starts."""

    def __init__(self, name: str, *, language: str, delay: float = 0.0) -> None:
        super().__init__(name=name)
        self.language = language
        self._delay = delay

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSUpdateSettingsFrame):
            # Applied inline by the switcher, like ServiceUpdateSettingsFrame on a real service.
            if getattr(frame.delta, "language", None):
                self.language = frame.delta.language
            return
        if isinstance(frame, TTSSpeakFrame):
            # Synthesised in order, as a real TTS does: end-of-stream waits for audio.
            await self._synthesise(frame.text, self.language)
            return
        await self.push_frame(frame, direction)

    async def _synthesise(self, text: str, language: str) -> None:
        await asyncio.sleep(self._delay)
        await self.push_frame(TextFrame(f"{self.name}:{language}:{text}"), FrameDirection.DOWNSTREAM)
        await self.push_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)


def _routes(service_for: dict[str, VoiceTTS]) -> dict[str, LanguageRoute]:
    return {
        lang: LanguageRoute(service=service, settings_delta=TTSSettings(language=lang))
        for lang, service in service_for.items()
    }


def _spoken(down: list[Frame]) -> list[str]:
    return [f.text for f in down if isinstance(f, TextFrame)]


class TestHandoffThroughTtsSwitcher(unittest.IsolatedAsyncioTestCase):
    async def test_shared_voice_speaks_handoff_in_the_old_language(self) -> None:
        """Hindi and Kannada are routes on one service, as in production."""
        voice = VoiceTTS("raya", language="hi", delay=0.05)
        switcher = ModelServiceSwitcher(
            kind="tts",
            services=[voice],
            routes=_routes({"hi": voice, "kn": voice}),
            primary_language="hi",
        )
        down, _up = await run_test(
            switcher,
            frames_to_send=[
                TTSSpeakFrame("ek minute", append_to_context=False),  # handoff for hi
                LanguageSwitchFrame(language="kn"),
                TTSSpeakFrame("namaskara"),  # the reply, in kn
            ],
        )
        self.assertEqual(_spoken(down), ["raya:hi:ek minute", "raya:kn:namaskara"])
        self.assertEqual(switcher.active_language, "kn")

    async def test_separate_voices_speak_handoff_in_the_old_language(self) -> None:
        hindi = VoiceTTS("hindi-tts", language="hi", delay=0.05)
        kannada = VoiceTTS("kannada-tts", language="kn")
        switcher = ModelServiceSwitcher(
            kind="tts",
            services=[hindi, kannada],
            routes=_routes({"hi": hindi, "kn": kannada}),
            primary_language="hi",
        )
        down, _up = await run_test(
            switcher,
            frames_to_send=[
                TTSSpeakFrame("ek minute", append_to_context=False),
                LanguageSwitchFrame(language="kn"),
                TTSSpeakFrame("namaskara"),
            ],
        )
        self.assertEqual(_spoken(down), ["hindi-tts:hi:ek minute", "kannada-tts:kn:namaskara"])

    async def test_switch_without_handoff_does_not_wait(self) -> None:
        voice = VoiceTTS("raya", language="hi", delay=0.0)
        switcher = ModelServiceSwitcher(
            kind="tts",
            services=[voice],
            routes=_routes({"hi": voice, "kn": voice}),
            primary_language="hi",
        )
        down, _up = await run_test(
            switcher,
            frames_to_send=[LanguageSwitchFrame(language="kn"), TTSSpeakFrame("namaskara")],
        )
        self.assertEqual(_spoken(down), ["raya:kn:namaskara"])


    async def test_a_voice_that_never_finishes_does_not_block_the_switch(self) -> None:
        class SilentVoice(VoiceTTS):
            async def _synthesise(self, text: str, language: str) -> None:
                await self.push_frame(TextFrame(f"{self.name}:{language}:{text}"), FrameDirection.DOWNSTREAM)

        voice = SilentVoice("raya", language="hi")
        switcher = ModelServiceSwitcher(
            kind="tts",
            services=[voice],
            routes=_routes({"hi": voice, "kn": voice}),
            primary_language="hi",
        )
        with mock.patch.object(switcher_module, "HANDOFF_SYNTH_WAIT_S", 0.1):
            down, _up = await run_test(
                switcher,
                frames_to_send=[
                    TTSSpeakFrame("ek minute", append_to_context=False),
                    LanguageSwitchFrame(language="kn"),
                    TTSSpeakFrame("namaskara"),
                ],
            )
        self.assertEqual(switcher.active_language, "kn")
        self.assertEqual(_spoken(down), ["raya:hi:ek minute", "raya:kn:namaskara"])


if __name__ == "__main__":
    unittest.main()
