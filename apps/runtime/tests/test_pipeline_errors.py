"""Unit tests for pipeline error handling."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

from pipecat.frames.frames import ErrorFrame
from pipecat.utils.errors import ErrorCategory
from starlette.websockets import WebSocketState

from apps.runtime.services.pipecat.events.errors import register_error_handlers


class _MockWorker:
    """Captures the handler `@worker.event_handler("on_pipeline_error")` binds."""

    def __init__(self) -> None:
        self.handler: Any = None

    def event_handler(self, name: str):
        assert name == "on_pipeline_error"

        def decorator(fn):
            self.handler = fn
            return fn

        return decorator


class _MockProcessor:
    def __init__(self, name: str, *, usable: bool) -> None:
        self.name = name
        self.is_usable = usable


class _MockWebSocket:
    def __init__(self, state: WebSocketState = WebSocketState.CONNECTED) -> None:
        self.application_state = state
        self.close = AsyncMock()


def _fire(websocket: Any, frame: ErrorFrame) -> None:
    worker = _MockWorker()
    register_error_handlers(worker, websocket, session_label="call_id=c1")
    asyncio.run(worker.handler(worker, frame))


def test_permanent_error_closes_with_internal_error_and_safe_reason() -> None:
    websocket = _MockWebSocket()
    _fire(
        websocket,
        ErrorFrame(
            error="Failed to connect to Sarvam: headers {'api-subscription-key': 'sk-secret'}",
            processor=_MockProcessor("SarvamSTTService#0", usable=False),
            category=ErrorCategory.AUTHORIZATION,
        ),
    )

    websocket.close.assert_awaited_once()
    kwargs = websocket.close.await_args.kwargs
    assert kwargs["code"] == 1011
    assert kwargs["reason"] == "SarvamSTTService#0: authorization"
    # Provider error text quotes the failing request, credentials included.
    assert "sk-secret" not in kwargs["reason"]


def test_recoverable_error_leaves_the_socket_open() -> None:
    websocket = _MockWebSocket()
    _fire(
        websocket,
        ErrorFrame(
            error="transient blip",
            processor=_MockProcessor("SarvamTTSService#0", usable=True),
            category=ErrorCategory.CONNECTIVITY,
        ),
    )

    websocket.close.assert_not_awaited()


def test_already_disconnected_socket_is_not_closed_again() -> None:
    websocket = _MockWebSocket(WebSocketState.DISCONNECTED)
    _fire(
        websocket,
        ErrorFrame(
            error="gone",
            processor=_MockProcessor("GroqLLMService#0", usable=False),
            category=ErrorCategory.INVALID_REQUEST,
        ),
    )

    websocket.close.assert_not_awaited()


def test_reason_is_clamped_to_the_close_frame_limit() -> None:
    websocket = _MockWebSocket()
    _fire(
        websocket,
        ErrorFrame(
            error="boom",
            processor=_MockProcessor("X" * 200, usable=False),
            category=ErrorCategory.SERVER,
        ),
    )

    reason = websocket.close.await_args.kwargs["reason"]
    assert len(reason.encode("utf-8")) <= 123


def test_error_without_processor_does_not_close() -> None:
    websocket = _MockWebSocket()
    _fire(websocket, ErrorFrame(error="no processor"))

    websocket.close.assert_not_awaited()
