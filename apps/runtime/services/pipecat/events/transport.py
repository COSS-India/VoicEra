"""Transport connect/disconnect handlers for the Pipecat pipeline."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.worker import PipelineWorker

from apps.runtime.services.pipecat.hold import HoldMessageHandler


def register_transport_handlers(
    transport: Any,
    worker: PipelineWorker,
    *,
    session_label: str,
    greeting: str,
    hold_handler: HoldMessageHandler | None,
) -> None:
    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport: Any, _client: Any) -> None:
        logger.info("Client connected {}", session_label)
        if greeting:
            logger.info("Queuing greeting ({} chars)", len(greeting))
            await worker.queue_frames([TTSSpeakFrame(greeting)])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport: Any, _client: Any) -> None:
        logger.info("Client disconnected {}", session_label)
        if hold_handler is not None:
            await hold_handler.cancel()
        await worker.cancel()
