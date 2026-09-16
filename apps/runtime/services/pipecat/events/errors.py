"""Pipeline error handlers — log the failure, tell the client it wasn't a hangup.

A service whose credentials or model are rejected marks itself unusable, and
the worker's ``ProcessorUnusablePolicy.END`` then ends the pipeline gracefully
(see ``factory.py``). Graceful means the endpoint returns normally and the
transport closes the socket with 1000, which a client cannot tell apart from a
call that simply finished. Closing here, while the pipeline is still draining,
is what makes the difference visible: 1011 plus the processor that gave up.

The close reason carries the processor name and error category only. Provider
error text routinely quotes the request that failed, headers included, so it is
logged and never sent downstream.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.frames.frames import ErrorFrame
from pipecat.pipeline.worker import PipelineWorker
from starlette.websockets import WebSocket, WebSocketState

# RFC 6455 caps a close frame's reason at 123 UTF-8 bytes.
_MAX_REASON_BYTES = 123
_INTERNAL_ERROR = 1011


def _truncate(reason: str) -> str:
    encoded = reason.encode("utf-8")
    if len(encoded) <= _MAX_REASON_BYTES:
        return reason
    return encoded[:_MAX_REASON_BYTES].decode("utf-8", "ignore")


async def _close(websocket: WebSocket, reason: str) -> None:
    if websocket.application_state is WebSocketState.DISCONNECTED:
        return
    try:
        await websocket.close(code=_INTERNAL_ERROR, reason=_truncate(reason))
    except Exception as exc:
        # The peer may have gone already; the pipeline is ending either way.
        logger.debug("Failed to close WebSocket after pipeline error: {}", exc)


def register_error_handlers(
    worker: PipelineWorker,
    websocket: WebSocket,
    *,
    session_label: str,
) -> None:
    """Log pipeline errors, and close on one a processor cannot recover from."""

    @worker.event_handler("on_pipeline_error")
    async def on_pipeline_error(_worker: Any, frame: ErrorFrame) -> None:
        processor = frame.processor
        name = processor.name if processor is not None else "pipeline"
        category = frame.category.value if frame.category is not None else "unknown"
        # A processor is already marked unusable by the time this fires, so
        # `is_usable` is the verdict on whether the error is permanent.
        permanent = processor is not None and not processor.is_usable

        log = logger.error if permanent else logger.warning
        log(
            "Pipeline error {} processor={} category={} permanent={}: {}",
            session_label,
            name,
            category,
            permanent,
            frame.error,
        )

        if permanent:
            await _close(websocket, f"{name}: {category}")
