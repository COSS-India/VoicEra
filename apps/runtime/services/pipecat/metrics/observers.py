"""Register Pipecat observers that feed a CallMetricsWriter.

See LATENCY_FIX_NOTES.md in this directory for the full writeup of the two
pipecat-ai 1.8.1 bugs ``_CorrectedUserBotLatencyObserver`` works around and
why they were corrected here rather than upstream or in the vendored
package.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger
from pipecat.frames.frames import LLMFullResponseStartFrame, LLMTextFrame
from pipecat.observers.base_observer import FramePushed
from pipecat.observers.startup_timing_observer import StartupTimingObserver
from pipecat.observers.turn_tracking_observer import TurnTrackingObserver
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.frame_processor import FrameDirection

from apps.runtime.services.pipecat.metrics.writer import CallMetricsWriter


def _attach_turn_tracking_handlers(
    turn_observer: TurnTrackingObserver,
    writer: CallMetricsWriter,
) -> None:
    @turn_observer.event_handler("on_turn_started")
    async def on_turn_started(_observer: Any, turn_count: int) -> None:
        writer.record_turn_started(turn_count)

    @turn_observer.event_handler("on_turn_ended")
    async def on_turn_ended(
        _observer: Any,
        turn_count: int,
        duration: float,
        was_interrupted: bool,
    ) -> None:
        writer.record_turn_ended(turn_count, duration, was_interrupted)


class _CorrectedUserBotLatencyObserver(UserBotLatencyObserver):
    """Fixes two pipecat-ai 1.8.1 bugs in ``UserBotLatencyObserver`` that were
    corrupting VoicERA's call-metrics dashboard. Full investigation in
    ``LATENCY_FIX_NOTES.md`` next to this file — short version below so the
    fix stays self-explanatory on its own.

    **Bug 1 — asymmetric reset on interruption.** Turns where the user
    genuinely spoke were showing up as "bot-initiated" with no STT/LLM/TTS
    stage data. Cause: the base class's ``_reset_accumulators()`` clears
    ``_ttfb`` and ``_user_turn_start_time`` on ``InterruptionFrame``, but
    leaves ``_user_stopped_time`` untouched. The next
    ``BotStartedSpeakingFrame`` then still reports a real
    ``on_latency_measured`` latency against an emptied breakdown — and
    because the dashboard treats a null ``user_turn_start_time`` as "no real
    user turn", it mislabels the row bot-initiated. Fix: make the reset
    symmetric by also clearing ``_user_stopped_time``.

    **Bug 2 — LLM "TTFB" measures stream-open, not first content token.**
    ``BaseOpenAILLMService._process_context()`` (pipecat's base OpenAI-
    compatible LLM service) stops the LLM's TTFB timer on the first streamed
    chunk with any ``choices`` at all. For an OpenAI-compatible chat
    completion that is always the empty role-preamble chunk
    (``delta: {"role": "assistant", "content": ""}``), which arrives a few
    ms after the request is sent — before the model has produced anything.
    That measures network/proxy round-trip, not "thinking time", which is
    what every consumer of this number (dashboard tile, per-turn table, CSV
    export) assumes it is. Fix: track ``LLMFullResponseStartFrame`` (pushed
    the instant the LLM call begins) through the first ``LLMTextFrame``
    carrying real text, and substitute that gap for the LLM-stage TTFB entry
    before it is bucketed into the per-turn breakdown — so every downstream
    consumer gets the corrected number for free, with no schema or frontend
    change.

    Known limitation on Bug 2: ``LLMFullResponseStartFrame``/``LLMTextFrame``
    don't carry a processor identity, so this assumes a single active LLM
    processor per call (true for every VoicERA agent today). A pipeline with
    two concurrent LLM stages couldn't be disambiguated this way.
    """

    def __init__(self, *, llm_processor_names: set[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._llm_processor_names = llm_processor_names
        self._llm_call_started_at: float | None = None
        self._pending_llm_content_ttfb: float | None = None

    def _reset_accumulators(self) -> None:
        super()._reset_accumulators()
        # Bug 1 fix: don't let a cancelled cycle's latency get attributed to
        # whichever bot utterance starts next.
        self._user_stopped_time = None
        # A cancelled cycle's in-flight LLM content-TTFB measurement is
        # equally stale — drop it for the same reason.
        self._llm_call_started_at = None
        self._pending_llm_content_ttfb = None

    async def on_push_frame(self, data: FramePushed) -> None:
        if data.direction == FrameDirection.DOWNSTREAM:
            if isinstance(data.frame, LLMFullResponseStartFrame):
                self._llm_call_started_at = data.timestamp
            elif (
                isinstance(data.frame, LLMTextFrame)
                and data.frame.text
                and self._llm_call_started_at is not None
            ):
                # Bug 2 fix: this is the first real output token — the gap
                # from LLMFullResponseStartFrame to here is the number
                # people mean by "LLM TTFB".
                self._pending_llm_content_ttfb = (
                    data.timestamp - self._llm_call_started_at
                ) / 1_000_000_000
                self._llm_call_started_at = None

        await super().on_push_frame(data)

    async def _handle_bot_started_speaking(self) -> None:
        # Patch the LLM-stage TTFB entry (if any) just before the base class
        # builds and emits the breakdown from self._ttfb. This has to happen
        # here rather than in _handle_metrics_frame: pipecat's own (wrong)
        # TTFBMetricsData is pushed and accumulated on the empty preamble
        # chunk, which always arrives *before* the real content chunk that
        # tells us the correct value (see class docstring, Bug 2) — so the
        # corrected number isn't known yet at the point the wrong one is
        # appended. By BotStartedSpeakingFrame time, both have long since
        # been processed (LLM text streaming finishes well before TTS
        # produces audio), so self._pending_llm_content_ttfb is reliably
        # populated here, and this observer's frames are handled strictly
        # in pipeline order (one queue per observer — see WorkerObserver),
        # so there's no cross-observer race to worry about either.
        pending = self._pending_llm_content_ttfb
        if pending is not None:
            for entry in self._ttfb:
                if entry.processor in self._llm_processor_names:
                    entry.duration_secs = pending
                    entry.start_time = time.time() - pending
            self._pending_llm_content_ttfb = None

        await super()._handle_bot_started_speaking()


def register_call_metrics(worker: PipelineWorker, writer: CallMetricsWriter) -> None:
    """Attach built-in Pipecat observers and wire them to ``writer``."""
    transport_observer = StartupTimingObserver()

    @transport_observer.event_handler("on_transport_timing_report")
    async def on_transport_timing_report(_observer: Any, report: Any) -> None:
        writer.record_transport_report(report)

    llm_processor_names = {
        name for name, stage in writer.processor_stages.items() if stage == "llm"
    }
    latency_observer = _CorrectedUserBotLatencyObserver(
        llm_processor_names=llm_processor_names
    )

    @latency_observer.event_handler("on_latency_measured")
    async def on_latency_measured(_observer: Any, latency_seconds: float) -> None:
        writer.record_user_bot_latency(latency_seconds)

    @latency_observer.event_handler("on_first_bot_speech_latency")
    async def on_first_bot_speech_latency(
        _observer: Any, latency_seconds: float
    ) -> None:
        writer.record_first_bot_speech_latency(latency_seconds)

    @latency_observer.event_handler("on_latency_breakdown")
    async def on_latency_breakdown(_observer: Any, breakdown: Any) -> None:
        writer.record_latency_breakdown(breakdown)

    observers: list[Any] = [transport_observer, latency_observer]

    turn_observer = getattr(worker, "turn_tracking_observer", None)
    if turn_observer is not None:
        _attach_turn_tracking_handlers(turn_observer, writer)
    else:
        turn_observer = TurnTrackingObserver()
        _attach_turn_tracking_handlers(turn_observer, writer)
        observers.append(turn_observer)

    for observer in observers:
        worker.add_observer(observer)

    logger.info("Call metrics observers registered call_id={}", writer.call_id)
