"""Unit tests for LidTapProcessor with a fake LID client."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

from pipecat.frames.frames import (
    InputAudioRawFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from apps.runtime.services.language_switch.frames import LanguageSwitchFrame
from apps.runtime.services.language_switch.lid.config import LidConfig
from apps.runtime.services.language_switch.lid.processor import LidTapProcessor
from apps.runtime.services.language_switch.lid.types import LidResult


class _FakeLidClient:
    def __init__(self, result: LidResult | None) -> None:
        self.result = result
        self.calls: list[bytes] = []

    async def identify(self, wav_bytes: bytes) -> LidResult | None:
        self.calls.append(wav_bytes)
        return self.result

    async def aclose(self) -> None:
        return None


def _pcm_seconds(seconds: float, sample_rate: int = 16_000) -> bytes:
    return b"\x00\x00" * int(sample_rate * seconds)


def _make_processor(
    client: _FakeLidClient,
    *,
    min_audio_sec: float = 1.8,
) -> LidTapProcessor:
    config = LidConfig(
        url="http://lid.test",
        min_confidence=0.7,
        min_audio_sec=min_audio_sec,
        cooldown_sec=0.0,
        timeout_s=2.0,
    )
    processor = LidTapProcessor(
        config=config,
        allowed_languages=["hi", "mr", "ta"],
        primary_language="hi",
        sample_rate=16_000,
        client=client,
    )
    pushed: list = []

    async def _capture(frame, direction):  # noqa: ANN001
        pushed.append((frame, direction))

    processor.push_frame = AsyncMock(side_effect=_capture)  # type: ignore[method-assign]
    processor._pushed = pushed  # type: ignore[attr-defined]
    return processor


def _switch_frames(processor: LidTapProcessor) -> list[LanguageSwitchFrame]:
    return [
        frame
        for frame, _direction in processor._pushed  # type: ignore[attr-defined]
        if isinstance(frame, LanguageSwitchFrame)
    ]


class TestLidTapProcessor(unittest.IsolatedAsyncioTestCase):
    async def test_audio_is_passed_through_immediately(self) -> None:
        client = _FakeLidClient(None)
        processor = _make_processor(client)
        frame = InputAudioRawFrame(audio=_pcm_seconds(0.1), sample_rate=16_000, num_channels=1)

        await processor.process_frame(
            VADUserStartedSpeakingFrame(),
            FrameDirection.DOWNSTREAM,
        )
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        # Start + audio both pushed; identify not awaited on the hop.
        self.assertGreaterEqual(len(processor._pushed), 2)  # type: ignore[attr-defined]
        self.assertIs(processor._pushed[-1][0], frame)  # type: ignore[attr-defined]
        self.assertEqual(client.calls, [])

    async def test_emits_switch_after_stop_when_confident(self) -> None:
        client = _FakeLidClient(LidResult(language_code="mr", confidence=0.95, duration_sec=2.0))
        processor = _make_processor(client)

        await processor.process_frame(
            VADUserStartedSpeakingFrame(),
            FrameDirection.DOWNSTREAM,
        )
        await processor.process_frame(
            InputAudioRawFrame(audio=_pcm_seconds(2.0), sample_rate=16_000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await processor.process_frame(
            VADUserStoppedSpeakingFrame(),
            FrameDirection.DOWNSTREAM,
        )

        switches: list[LanguageSwitchFrame] = []
        for _ in range(40):
            switches = _switch_frames(processor)
            if switches:
                break
            await asyncio.sleep(0.05)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(switches), 1)
        self.assertEqual(switches[0].language, "mr")
        self.assertEqual(processor.active_language, "mr")

    async def test_short_audio_does_not_identify(self) -> None:
        client = _FakeLidClient(LidResult(language_code="mr", confidence=0.95))
        processor = _make_processor(client, min_audio_sec=1.8)

        await processor.process_frame(
            VADUserStartedSpeakingFrame(),
            FrameDirection.DOWNSTREAM,
        )
        await processor.process_frame(
            InputAudioRawFrame(audio=_pcm_seconds(0.5), sample_rate=16_000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await processor.process_frame(
            VADUserStoppedSpeakingFrame(),
            FrameDirection.DOWNSTREAM,
        )
        await asyncio.sleep(0.05)

        self.assertEqual(client.calls, [])
        self.assertEqual(_switch_frames(processor), [])

    async def test_observed_language_switch_frame_updates_active(self) -> None:
        client = _FakeLidClient(None)
        processor = _make_processor(client)

        await processor.process_frame(
            LanguageSwitchFrame(language="ta"),
            FrameDirection.DOWNSTREAM,
        )
        self.assertEqual(processor.active_language, "ta")

    async def test_stay_when_same_as_primary(self) -> None:
        client = _FakeLidClient(LidResult(language_code="hi", confidence=0.99))
        processor = _make_processor(client)

        await processor.process_frame(
            VADUserStartedSpeakingFrame(),
            FrameDirection.DOWNSTREAM,
        )
        await processor.process_frame(
            InputAudioRawFrame(audio=_pcm_seconds(2.0), sample_rate=16_000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await processor.process_frame(
            VADUserStoppedSpeakingFrame(),
            FrameDirection.DOWNSTREAM,
        )
        await asyncio.sleep(0.1)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(_switch_frames(processor), [])
        self.assertEqual(processor.active_language, "hi")

    async def test_upstream_vad_with_downstream_audio_emits_switch(self) -> None:
        """Aggregator-owned Silero broadcasts VAD upstream; audio stays downstream."""
        client = _FakeLidClient(LidResult(language_code="ta", confidence=0.92, duration_sec=2.0))
        processor = _make_processor(client)

        await processor.process_frame(
            VADUserStartedSpeakingFrame(),
            FrameDirection.UPSTREAM,
        )
        await processor.process_frame(
            InputAudioRawFrame(audio=_pcm_seconds(2.0), sample_rate=16_000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await processor.process_frame(
            VADUserStoppedSpeakingFrame(),
            FrameDirection.UPSTREAM,
        )

        switches: list[LanguageSwitchFrame] = []
        for _ in range(40):
            switches = _switch_frames(processor)
            if switches:
                break
            await asyncio.sleep(0.05)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(switches), 1)
        self.assertEqual(switches[0].language, "ta")
        self.assertEqual(processor.active_language, "ta")

    async def test_idle_audio_is_trimmed_to_preroll_without_start(self) -> None:
        client = _FakeLidClient(LidResult(language_code="mr", confidence=0.95))
        processor = _make_processor(client, min_audio_sec=1.8)

        # Idle capture keeps only a short pre-roll; stop without start stays short.
        await processor.process_frame(
            InputAudioRawFrame(audio=_pcm_seconds(2.0), sample_rate=16_000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await processor.process_frame(
            VADUserStoppedSpeakingFrame(),
            FrameDirection.UPSTREAM,
        )
        await asyncio.sleep(0.05)

        self.assertEqual(client.calls, [])
        self.assertEqual(_switch_frames(processor), [])

    async def test_preroll_plus_speech_after_late_upstream_start(self) -> None:
        client = _FakeLidClient(LidResult(language_code="ta", confidence=0.9, duration_sec=2.0))
        processor = _make_processor(client, min_audio_sec=1.8)

        # Pre-roll while idle (capped), then late VAD start, then more speech.
        await processor.process_frame(
            InputAudioRawFrame(audio=_pcm_seconds(0.4), sample_rate=16_000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await processor.process_frame(
            VADUserStartedSpeakingFrame(),
            FrameDirection.UPSTREAM,
        )
        await processor.process_frame(
            InputAudioRawFrame(audio=_pcm_seconds(1.5), sample_rate=16_000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await processor.process_frame(
            VADUserStoppedSpeakingFrame(),
            FrameDirection.UPSTREAM,
        )

        switches: list[LanguageSwitchFrame] = []
        for _ in range(40):
            switches = _switch_frames(processor)
            if switches:
                break
            await asyncio.sleep(0.05)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(switches), 1)
        self.assertEqual(switches[0].language, "ta")


class TestResolveLidConfig(unittest.TestCase):
    def test_mode_and_url_gating(self) -> None:
        from apps.runtime.services.language_switch.lid.config import (
            language_switching_mode,
            resolve_lid_config,
        )
        import os
        from unittest.mock import patch

        self.assertEqual(language_switching_mode({}), "deterministic")
        self.assertEqual(
            language_switching_mode({"language_switching_mode": "lid"}),
            "lid",
        )

        lid_behaviour = {"language_switching_mode": "lid"}

        # Default deterministic → no LID even with URL.
        with patch.dict(os.environ, {"NEMOTRON_LID_URL": "http://127.0.0.1:8765"}):
            self.assertIsNone(resolve_lid_config({}, multilingual=True))
            self.assertIsNone(
                resolve_lid_config(
                    {"language_switching_mode": "deterministic"},
                    multilingual=True,
                )
            )

        # LID mode without URL → None (fail closed).
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEMOTRON_LID_URL", None)
            self.assertIsNone(resolve_lid_config(lid_behaviour, multilingual=True))

        # LID mode + URL + multilingual → config.
        with patch.dict(os.environ, {"NEMOTRON_LID_URL": "http://127.0.0.1:8765"}):
            self.assertIsNone(resolve_lid_config(lid_behaviour, multilingual=False))
            cfg = resolve_lid_config(lid_behaviour, multilingual=True)
            self.assertIsNotNone(cfg)
            assert cfg is not None
            self.assertEqual(cfg.url, "http://127.0.0.1:8765")


if __name__ == "__main__":
    unittest.main()
