"""Register Pipecat observers that feed a CallMetricsWriter."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.observers.startup_timing_observer import StartupTimingObserver
from pipecat.observers.turn_tracking_observer import TurnTrackingObserver
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.pipeline.worker import PipelineWorker

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


def register_call_metrics(worker: PipelineWorker, writer: CallMetricsWriter) -> None:
    """Attach built-in Pipecat observers and wire them to ``writer``."""
    transport_observer = StartupTimingObserver()

    @transport_observer.event_handler("on_transport_timing_report")
    async def on_transport_timing_report(_observer: Any, report: Any) -> None:
        writer.record_transport_report(report)

    latency_observer = UserBotLatencyObserver()

    @latency_observer.event_handler("on_latency_measured")
    async def on_latency_measured(_observer: Any, latency_seconds: float) -> None:
        writer.record_user_bot_latency(latency_seconds)

    @latency_observer.event_handler("on_first_bot_speech_latency")
    async def on_first_bot_speech_latency(_observer: Any, latency_seconds: float) -> None:
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
