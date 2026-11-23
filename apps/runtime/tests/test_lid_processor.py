"""Unit tests for the end-of-utterance LidTapProcessor (Nemotron transcript tap)."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from pipecat.frames.frames import (
    InputAudioRawFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from apps.runtime.services.language_switch.frames import NemotronTranscriptFrame
from apps.runtime.services.language_switch.lid.processor import LidTapProcessor


class _FakeNemotron:
    def __init__(self, text: str = "", *, delay: float = 0.0) -> None:
        self.text = text
        self.delay = delay
        self.calls: list[bytes] = []
        self.closed = False

    async def transcribe(self, wav_bytes: bytes) -> str:
        self.calls.append(wav_bytes)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.text

    async def aclose(self) -> None:
        self.closed = True


def _audio(seconds: float) -> InputAudioRawFrame:
    pcm = b"\x00\x00" * int(16_000 * seconds)
    return InputAudioRawFrame(audio=pcm, sample_rate=16_000, num_channels=1)


def _make(client: _FakeNemotron) -> LidTapProcessor:
    processor = LidTapProcessor(client=client, sample_rate=16_000)
    pushed: list = []

    async def _capture(frame, direction):  # noqa: ANN001
        pushed.append(frame)

    processor.push_frame = AsyncMock(side_effect=_capture)  # type: ignore[method-assign]
    processor._pushed = pushed  # type: ignore[attr-defined]
    return processor


def _transcripts(processor: LidTapProcessor) -> list[str]:
    return [
        f.text for f in processor._pushed if isinstance(f, NemotronTranscriptFrame)  # type: ignore[attr-defined]
    ]


async def _speak(processor: LidTapProcessor, seconds: float, *, stop: bool = True) -> None:
    # The aggregator broadcasts VAD frames upstream.
    await processor.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    await processor.process_frame(_audio(seconds), FrameDirection.DOWNSTREAM)
    if stop:
        await processor.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.UPSTREAM)


async def _settle(processor: LidTapProcessor) -> None:
    if processor._task is not None:  # type: ignore[attr-defined]
        await asyncio.wait_for(processor._task, timeout=2.0)  # type: ignore[attr-defined]


class TestLidTapProcessor(unittest.IsolatedAsyncioTestCase):
    async def test_audio_is_passed_through(self) -> None:
        processor = _make(_FakeNemotron())
        frame = _audio(0.1)
        await processor.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        self.assertIs(processor._pushed[-1], frame)  # type: ignore[attr-defined]

    async def test_every_utterance_is_transcribed_at_speech_stop(self) -> None:
        client = _FakeNemotron("ನಮಸ್ಕಾರ ನೀವು ಹೇಗಿದ್ದೀರಿ")
        processor = _make(client)
        await _speak(processor, 1.5, stop=False)
        self.assertEqual(client.calls, [])  # nothing until end of speech

        await processor.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _settle(processor)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(_transcripts(processor), ["ನಮಸ್ಕಾರ ನೀವು ಹೇಗಿದ್ದೀರಿ"])

    async def test_short_burst_skips_nemotron_but_still_emits_one_frame(self) -> None:
        client = _FakeNemotron("x")
        processor = _make(client)
        await _speak(processor, 0.2)

        self.assertEqual(client.calls, [])
        self.assertEqual(_transcripts(processor), [""])

    async def test_failure_emits_empty_transcript(self) -> None:
        processor = _make(_FakeNemotron(""))
        await _speak(processor, 2.0)
        await _settle(processor)
        self.assertEqual(_transcripts(processor), [""])

    async def test_new_speech_cancels_inflight_call(self) -> None:
        client = _FakeNemotron("late", delay=5.0)
        processor = _make(client)
        await _speak(processor, 2.0)
        await asyncio.sleep(0.05)
        await processor.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.UPSTREAM)

        self.assertEqual(_transcripts(processor), [""])  # superseded, never "late"

    async def test_shutdown_closes_client_and_emits_nothing(self) -> None:
        from pipecat.frames.frames import EndFrame

        client = _FakeNemotron("late", delay=5.0)
        processor = _make(client)
        await _speak(processor, 2.0)
        await asyncio.sleep(0.05)
        await processor.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)

        self.assertTrue(client.closed)
        self.assertEqual(_transcripts(processor), [])


class TestResolveLidConfig(unittest.TestCase):
    ENV = {"NEMOTRON_LID_URL": "http://127.0.0.1:8100/v1/lid/", "INDICLID_URL": "http://indic:8090/"}

    def test_mode_and_multilingual_gating(self) -> None:
        from apps.runtime.services.language_switch.lid.config import (
            language_switching_mode,
            resolve_lid_config,
        )

        self.assertEqual(language_switching_mode({}), "deterministic")
        self.assertEqual(language_switching_mode({"language_switching_mode": "lid"}), "lid")

        lid = {"language_switching_mode": "lid"}
        with patch.dict(os.environ, self.ENV):
            self.assertIsNone(resolve_lid_config({}, multilingual=True))
            self.assertIsNone(
                resolve_lid_config({"language_switching_mode": "deterministic"}, multilingual=True)
            )
            self.assertIsNone(resolve_lid_config(lid, multilingual=False))

    def test_both_urls_are_required(self) -> None:
        from apps.runtime.services.language_switch.lid.config import resolve_lid_config

        lid = {"language_switching_mode": "lid"}
        for missing in self.ENV:
            env = {k: v for k, v in self.ENV.items() if k != missing}
            with patch.dict(os.environ, env, clear=True):
                self.assertIsNone(resolve_lid_config(lid, multilingual=True), missing)

    def test_defaults_and_overrides(self) -> None:
        from apps.runtime.services.language_switch.lid.config import resolve_lid_config

        lid = {"language_switching_mode": "lid"}
        with patch.dict(os.environ, self.ENV, clear=True):
            cfg = resolve_lid_config(lid, multilingual=True)
            assert cfg is not None
            self.assertEqual(cfg.nemotron_url, "http://127.0.0.1:8100/v1/lid")
            self.assertEqual(cfg.indiclid_url, "http://indic:8090")
            self.assertEqual(
                (cfg.min_words, cfg.min_score, cfg.margin, cfg.cooldown_sec), (3, 0.8, 0.3, 3.0)
            )
            self.assertGreater(cfg.hold_deadline_s, cfg.nemotron_timeout_s)
            self.assertEqual(cfg.handoff_messages, {})

            cfg = resolve_lid_config(
                {**lid, "lid": {"min_words": 5, "min_score": 0.9, "margin": 0.5}},
                multilingual=True,
            )
            assert cfg is not None
            self.assertEqual((cfg.min_words, cfg.min_score, cfg.margin), (5, 0.9, 0.5))

            cfg = resolve_lid_config(
                {
                    **lid,
                    "lid": {
                        "handoff_messages": {
                            " HI-IN ": "  Ek minute  ",
                            "kn": "ಒಂದು ನಿಮಿಷ",
                            "ta": "   ",
                            "": "no key",
                        }
                    },
                },
                multilingual=True,
            )
            assert cfg is not None
            self.assertEqual(cfg.handoff_messages, {"hi": "Ek minute", "kn": "ಒಂದು ನಿಮಿಷ"})

            for bad in (None, "text", ["hi"]):
                cfg = resolve_lid_config(
                    {**lid, "lid": {"handoff_messages": bad}}, multilingual=True
                )
                assert cfg is not None
                self.assertEqual(cfg.handoff_messages, {})


if __name__ == "__main__":
    unittest.main()
