"""Regression tests for ``_CorrectedUserBotLatencyObserver``.

See LATENCY_FIX_NOTES.md in apps/runtime/services/pipecat/metrics/ for the
full writeup of the two pipecat-ai 1.8.1 bugs these tests pin down.
"""

from __future__ import annotations

import asyncio

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    InterruptionFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    MetricsFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection

from apps.runtime.services.pipecat.metrics.observers import (
    _CorrectedUserBotLatencyObserver,
)


class _Clock:
    """Monotonically increasing fake pipeline-clock (nanoseconds)."""

    def __init__(self) -> None:
        self._now = 0

    def push(
        self, frame, direction=FrameDirection.DOWNSTREAM, step_secs: float = 1.0
    ) -> FramePushed:
        self._now += int(step_secs * 1_000_000_000)
        return FramePushed(
            source=None,
            destination=None,
            frame=frame,
            direction=direction,
            timestamp=self._now,
        )


def _observer() -> _CorrectedUserBotLatencyObserver:
    return _CorrectedUserBotLatencyObserver(
        llm_processor_names={"MyLLM"}, stt_processor_names={"MySTT"}
    )


async def _feed(
    observer: _CorrectedUserBotLatencyObserver, clock: _Clock, frames
) -> None:
    for frame in frames:
        await observer.on_push_frame(clock.push(frame))


@pytest.mark.asyncio
async def test_llm_ttfb_corrected_to_first_content_token() -> None:
    """The LLM-stage TTFB reported in the breakdown should be the gap to the
    first real content token, not to OpenAI's empty role-preamble chunk."""
    observer = _observer()
    breakdowns = []

    @observer.event_handler("on_latency_breakdown")
    async def _capture(_observer, breakdown) -> None:
        breakdowns.append(breakdown)

    clock = _Clock()
    await _feed(
        observer,
        clock,
        [
            VADUserStoppedSpeakingFrame(stop_secs=0.0),
            LLMFullResponseStartFrame(),
            # Pipecat's own (wrong) TTFB: fires on the empty preamble chunk,
            # a few ms after the LLM call starts.
            MetricsFrame(
                data=[TTFBMetricsData(processor="MyLLM", value=0.008, model="gpt")]
            ),
            # The real first content token arrives later.
            LLMTextFrame(text="Hello there"),
            BotStartedSpeakingFrame(),
        ],
    )
    await asyncio.sleep(0.02)  # let the scheduled event-handler task run

    assert len(breakdowns) == 1
    breakdown = breakdowns[0]
    assert breakdown.user_turn_start_time is not None

    llm_entries = [entry for entry in breakdown.ttfb if entry.processor == "MyLLM"]
    assert len(llm_entries) == 1
    # Two frame-pushes (1s each, per _Clock's default step) separate
    # LLMFullResponseStartFrame from LLMTextFrame, so the corrected value is
    # ~2.0s — nowhere near the original 0.008s from the preamble chunk.
    assert llm_entries[0].duration_secs == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_turn_start_interruption_keeps_current_user_turn() -> None:
    """With a transcript-gated turn-start strategy (MinWords), the user turn's
    own InterruptionFrame arrives *after* VADUserStoppedSpeakingFrame. It must
    not wipe that turn's user timing or STT entry — only what the interrupted
    bot response left behind (here a stale TTS TTFB).

    Before the fix the turn was either labelled bot-initiated with no STT
    (stock pipecat) or dropped from telemetry entirely (an earlier version of
    this observer that also cleared _user_stopped_time).
    """
    observer = _observer()
    breakdowns = []
    latencies = []

    @observer.event_handler("on_latency_breakdown")
    async def _capture_breakdown(_observer, breakdown) -> None:
        breakdowns.append(breakdown)

    @observer.event_handler("on_latency_measured")
    async def _capture_latency(_observer, latency_seconds) -> None:
        latencies.append(latency_seconds)

    clock = _Clock()
    await _feed(
        observer,
        clock,
        [
            VADUserStoppedSpeakingFrame(stop_secs=0.0),
            # Leftover from the bot response still being synthesized.
            MetricsFrame(data=[TTFBMetricsData(processor="MyTTS", value=0.99)]),
            MetricsFrame(data=[TTFBMetricsData(processor="MySTT", value=0.3)]),
            InterruptionFrame(),
            MetricsFrame(
                data=[TTFBMetricsData(processor="MyLLM", value=0.4, model="gpt")]
            ),
            MetricsFrame(data=[TTFBMetricsData(processor="MyTTS", value=0.2)]),
            BotStartedSpeakingFrame(),
        ],
    )
    await asyncio.sleep(0.02)  # let the scheduled event-handler tasks run

    assert len(latencies) == 1
    assert len(breakdowns) == 1
    breakdown = breakdowns[0]
    assert breakdown.user_turn_start_time is not None
    assert [(e.processor, e.duration_secs) for e in breakdown.ttfb] == [
        ("MySTT", pytest.approx(0.3)),
        ("MyLLM", pytest.approx(0.4)),
        ("MyTTS", pytest.approx(0.2)),
    ]


@pytest.mark.asyncio
async def test_new_user_speech_still_discards_cancelled_cycle() -> None:
    """If the user speaks again before the bot answers, the abandoned cycle
    must not be reported against the next bot utterance."""
    observer = _observer()
    breakdowns = []
    latencies = []

    @observer.event_handler("on_latency_breakdown")
    async def _capture_breakdown(_observer, breakdown) -> None:
        breakdowns.append(breakdown)

    @observer.event_handler("on_latency_measured")
    async def _capture_latency(_observer, latency_seconds) -> None:
        latencies.append(latency_seconds)

    clock = _Clock()
    await _feed(
        observer,
        clock,
        [
            VADUserStoppedSpeakingFrame(stop_secs=0.0),
            MetricsFrame(
                data=[TTFBMetricsData(processor="MyLLM", value=0.4, model="gpt")]
            ),
            VADUserStartedSpeakingFrame(),
            InterruptionFrame(),
            BotStartedSpeakingFrame(),
        ],
    )
    await asyncio.sleep(0.02)  # let any scheduled event-handler task run

    assert breakdowns == []
    assert latencies == []
