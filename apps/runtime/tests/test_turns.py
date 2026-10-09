"""Turn release timing for FinalizedTranscriptUserTurnStopStrategy.

Drives a real pipecat user aggregator with the frame order a MinWords agent
sees on every turn: VAD stop first, transcript ~0.1s later. Measures how long
after the transcript the user turn is released to the LLM.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from pipecat.audio.turn.base_turn_analyzer import (
    BaseTurnAnalyzer,
    BaseTurnParams,
    EndOfTurnState,
)
from pipecat.frames.frames import (
    EndFrame,
    STTMetadataFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.turns.user_start import (
    MinWordsUserTurnStartStrategy,
    VADUserTurnStartStrategy,
)
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.utils.time import time_now_iso8601
from pipecat.workers.runner import WorkerRunner

from apps.runtime.services.pipecat.turns import FinalizedTranscriptUserTurnStopStrategy

# Pipecat's default STT P99 and VoicEra's default VAD stop_secs: the fallback
# timer is 1.0 - 0.4 = 0.6s.
_TTFS_P99 = 1.0
_STOP_SECS = 0.4
_FALLBACK_WAIT = _TTFS_P99 - _STOP_SECS


class _StubAnalyzer(BaseTurnAnalyzer):
    """Stands in for Smart Turn v3 with a fixed end-of-turn prediction."""

    def __init__(self, state: EndOfTurnState) -> None:
        super().__init__()
        self._state = state

    @property
    def speech_triggered(self) -> bool:
        return False

    @property
    def params(self) -> BaseTurnParams:
        return BaseTurnParams()

    def append_audio(self, buffer: bytes, is_speech: bool) -> EndOfTurnState:
        return EndOfTurnState.INCOMPLETE

    async def analyze_end_of_turn(self):
        return self._state, None

    def clear(self) -> None:
        pass


async def _release_delay(
    start,
    stop_cls,
    *,
    finalized: bool,
    prediction: EndOfTurnState = EndOfTurnState.COMPLETE,
) -> float | None:
    """Seconds from the transcript to user-turn release, or None if not released."""
    stop = stop_cls(turn_analyzer=_StubAnalyzer(prediction))
    user, _ = LLMContextAggregatorPair(
        LLMContext([]),
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(start=[start], stop=[stop])
        ),
    )
    times: dict[str, float] = {}

    @user.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped(*_args) -> None:
        times.setdefault("released", time.monotonic())

    worker = PipelineWorker(Pipeline([user]), params=PipelineParams(), idle_timeout_secs=None)

    async def queue(frame, delay: float = 0.05) -> None:
        await worker.queue_frame(frame)
        await asyncio.sleep(delay)

    async def drive() -> None:
        await asyncio.sleep(0.2)
        await queue(STTMetadataFrame(service_name="stt", ttfs_p99_latency=_TTFS_P99))
        await queue(VADUserStartedSpeakingFrame())
        await queue(VADUserStoppedSpeakingFrame(stop_secs=_STOP_SECS), 0.1)
        transcript = TranscriptionFrame("enthanu scholarship handbook", "u", time_now_iso8601())
        transcript.finalized = finalized
        times["transcript"] = time.monotonic()
        await queue(transcript, _FALLBACK_WAIT + 0.3)
        await queue(EndFrame())

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await asyncio.gather(runner.run(), drive())
    if "released" not in times:
        return None
    return times["released"] - times["transcript"]


def _min_words():
    return MinWordsUserTurnStartStrategy(min_words=2)


@pytest.mark.asyncio
async def test_stock_strategy_idles_min_words_turn_on_fallback_timer() -> None:
    # Documents the pipecat bug this module works around. If this starts
    # failing after a pipecat upgrade, the subclass may no longer be needed.
    delay = await _release_delay(
        _min_words(), TurnAnalyzerUserTurnStopStrategy, finalized=True
    )
    assert delay is not None and delay >= _FALLBACK_WAIT - 0.05


@pytest.mark.asyncio
async def test_min_words_finalized_transcript_releases_immediately() -> None:
    delay = await _release_delay(
        _min_words(), FinalizedTranscriptUserTurnStopStrategy, finalized=True
    )
    assert delay is not None and delay < 0.1


@pytest.mark.asyncio
async def test_min_words_non_finalized_transcript_keeps_fallback_timer() -> None:
    delay = await _release_delay(
        _min_words(), FinalizedTranscriptUserTurnStopStrategy, finalized=False
    )
    assert delay is not None and delay >= _FALLBACK_WAIT - 0.05


@pytest.mark.asyncio
async def test_min_words_release_still_ignores_smart_turn_prediction() -> None:
    # MinWords turns never used the Smart Turn verdict (the turn-start reset
    # drops it); releasing on finalized must not make them start waiting on it.
    delay = await _release_delay(
        _min_words(),
        FinalizedTranscriptUserTurnStopStrategy,
        finalized=True,
        prediction=EndOfTurnState.INCOMPLETE,
    )
    assert delay is not None and delay < 0.1


@pytest.mark.asyncio
async def test_vad_start_finalized_transcript_unchanged() -> None:
    delay = await _release_delay(
        VADUserTurnStartStrategy(), FinalizedTranscriptUserTurnStopStrategy, finalized=True
    )
    assert delay is not None and delay < 0.1
