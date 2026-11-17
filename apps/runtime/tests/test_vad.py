"""Unit tests for Silero VAD params and speaking/idle profile switching."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection

from apps.runtime.services.pipecat.vad import (
    DEFAULT_VAD,
    VadProfileSwitcher,
    vad_params_from_behaviour,
)


class _FakeAnalyzer:
    def __init__(self, params: VADParams) -> None:
        self.params = params
        self.set_calls: list[VADParams] = []

    def set_params(self, params: VADParams) -> None:
        self.params = params
        self.set_calls.append(params)


def test_vad_params_missing_uses_defaults() -> None:
    params = vad_params_from_behaviour({})
    assert params.confidence == DEFAULT_VAD["confidence"]
    assert params.start_secs == DEFAULT_VAD["start_secs"]
    assert params.stop_secs == DEFAULT_VAD["stop_secs"]
    assert params.min_volume == DEFAULT_VAD["min_volume"]


def test_vad_params_empty_vad_uses_defaults() -> None:
    params = vad_params_from_behaviour({"vad": {}})
    assert params.confidence == DEFAULT_VAD["confidence"]
    assert params.start_secs == DEFAULT_VAD["start_secs"]
    assert params.stop_secs == DEFAULT_VAD["stop_secs"]
    assert params.min_volume == DEFAULT_VAD["min_volume"]


def test_vad_params_partial_override() -> None:
    params = vad_params_from_behaviour({"vad": {"confidence": 0.7, "stop_secs": 0.8}})
    assert params.confidence == 0.7
    assert params.stop_secs == 0.8
    assert params.start_secs == DEFAULT_VAD["start_secs"]
    assert params.min_volume == DEFAULT_VAD["min_volume"]


def test_vad_params_full_override() -> None:
    params = vad_params_from_behaviour(
        {
            "vad": {
                "confidence": 0.6,
                "start_secs": 0.2,
                "stop_secs": 0.5,
                "min_volume": 0.4,
            }
        }
    )
    assert params.confidence == 0.6
    assert params.start_secs == 0.2
    assert params.stop_secs == 0.5
    assert params.min_volume == 0.4


def test_vad_idle_params_from_behaviour() -> None:
    params = vad_params_from_behaviour(
        {
            "vad_idle": {
                "confidence": 0.2,
                "start_secs": 0.1,
                "stop_secs": 0.3,
                "min_volume": 0.4,
            }
        },
        key="vad_idle",
    )
    assert params.confidence == 0.2
    assert params.stop_secs == 0.3
    assert params.min_volume == 0.4


def test_vad_idle_missing_uses_defaults() -> None:
    params = vad_params_from_behaviour({}, key="vad_idle")
    assert params.confidence == DEFAULT_VAD["confidence"]
    assert params.min_volume == DEFAULT_VAD["min_volume"]


def test_vad_profile_switcher_swaps_on_bot_speaking_frames() -> None:
    speaking = VADParams(confidence=0.7, start_secs=0.2, stop_secs=0.5, min_volume=0.6)
    idle = VADParams(confidence=0.2, start_secs=0.1, stop_secs=0.3, min_volume=0.4)
    analyzer = _FakeAnalyzer(idle)
    switcher = VadProfileSwitcher(analyzer, speaking=speaking, idle=idle)  # type: ignore[arg-type]
    switcher.push_frame = AsyncMock()  # type: ignore[method-assign]

    async def _run() -> None:
        await switcher.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        assert analyzer.params == speaking
        assert analyzer.set_calls == [speaking]

        await switcher.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        assert analyzer.params == idle
        assert analyzer.set_calls == [speaking, idle]

    asyncio.run(_run())


def test_vad_profile_switcher_ignores_duplicate_bot_started() -> None:
    speaking = VADParams(confidence=0.7, start_secs=0.2, stop_secs=0.5, min_volume=0.6)
    idle = VADParams(confidence=0.2, start_secs=0.1, stop_secs=0.3, min_volume=0.4)
    analyzer = _FakeAnalyzer(idle)
    switcher = VadProfileSwitcher(analyzer, speaking=speaking, idle=idle)  # type: ignore[arg-type]
    switcher.push_frame = AsyncMock()  # type: ignore[method-assign]

    async def _run() -> None:
        await switcher.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        await switcher.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        assert analyzer.set_calls == [speaking]

    asyncio.run(_run())
