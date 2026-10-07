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


async def _feed(
    observer: _CorrectedUserBotLatencyObserver, clock: _Clock, frames
) -> None:
    for frame in frames:
        await observer.on_push_frame(clock.push(frame))


@pytest.mark.asyncio
async def test_llm_ttfb_corrected_to_first_content_token() -> None:
    """The LLM-stage TTFB reported in the breakdown should be the gap to the
    first real content token, not to OpenAI's empty role-preamble chunk."""
    observer = _CorrectedUserBotLatencyObserver(llm_processor_names={"MyLLM"})
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
async def test_interruption_does_not_leak_stale_latency() -> None:
    """A cycle cancelled by InterruptionFrame before the bot actually speaks
    must not surface a latency/breakdown for whatever bot utterance follows.

    Before the fix, pipecat's _reset_accumulators() cleared ttfb/
    user_turn_start_time on InterruptionFrame but left _user_stopped_time
    untouched, so the *next* BotStartedSpeakingFrame still fired
    on_latency_measured() with a real number against an empty breakdown —
    which the dashboard then displayed as a "bot-initiated" turn with no
    stage data, even though the user had genuinely spoken.
    """
    observer = _CorrectedUserBotLatencyObserver(llm_processor_names={"MyLLM"})
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
            LLMFullResponseStartFrame(),
            MetricsFrame(
                data=[TTFBMetricsData(processor="MyLLM", value=0.009, model="gpt")]
            ),
            InterruptionFrame(),
            # Whatever bot utterance follows the interruption shouldn't be
            # reported against the cancelled cycle's (now stale) state.
            BotStartedSpeakingFrame(),
        ],
    )
    await asyncio.sleep(0.02)  # let any scheduled event-handler task run

    assert breakdowns == []
    assert latencies == []
