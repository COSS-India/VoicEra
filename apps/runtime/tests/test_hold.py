"""Unit tests for LLM hold message handling."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pipecat.frames.frames import TTSSpeakFrame

from apps.runtime.services.pipecat.hold import HoldMessageHandler, hold_from_behaviour


class _MockTts:
    def __init__(self) -> None:
        self.queue_frame = AsyncMock()


@pytest.mark.parametrize(
    "behaviour",
    [
        {},
        {"hold_messages": [], "hold_message_timeout_seconds": 0.6},
        {"hold_messages": ["Wait"], "hold_message_timeout_seconds": None},
        {"hold_messages": ["Wait"], "hold_message_timeout_seconds": 0},
    ],
)
def test_hold_from_behaviour_disabled(behaviour: dict[str, Any]) -> None:
    assert hold_from_behaviour(behaviour, _MockTts()) is None


def test_hold_from_behaviour_enabled() -> None:
    handler = hold_from_behaviour(
        {
            "hold_messages": ["One moment please.", "  "],
            "hold_message_timeout_seconds": 0.6,
        },
        _MockTts(),
    )
    assert handler is not None
    assert handler._messages == ["One moment please."]
    assert handler._timeout_seconds == 0.6


@pytest.mark.asyncio
async def test_hold_plays_after_timeout() -> None:
    tts = _MockTts()
    handler = HoldMessageHandler(
        messages=["One moment please."],
        timeout_seconds=0.05,
        tts=tts,
    )

    with patch(
        "apps.runtime.services.pipecat.hold.random.choice",
        return_value="One moment please.",
    ):
        await handler.on_inference_started()
        await asyncio.sleep(0.1)

    tts.queue_frame.assert_awaited_once()
    frame = tts.queue_frame.await_args.args[0]
    assert isinstance(frame, TTSSpeakFrame)
    assert frame.text == "One moment please."
    assert frame.append_to_context is False


@pytest.mark.asyncio
async def test_hold_cancelled_on_response() -> None:
    """Simulates first LLM TextFrame arriving after timer started but before timeout."""
    tts = _MockTts()
    handler = HoldMessageHandler(
        messages=["One moment please."],
        timeout_seconds=0.2,
        tts=tts,
    )

    await handler.on_inference_started()
    await asyncio.sleep(0.05)
    await handler.cancel()
    await asyncio.sleep(0.2)

    tts.queue_frame.assert_not_awaited()


@pytest.mark.asyncio
async def test_hold_cancelled_before_timeout() -> None:
    tts = _MockTts()
    handler = HoldMessageHandler(
        messages=["One moment please."],
        timeout_seconds=0.2,
        tts=tts,
    )

    await handler.on_inference_started()
    await handler.cancel()
    await asyncio.sleep(0.25)

    tts.queue_frame.assert_not_awaited()


@pytest.mark.asyncio
async def test_hold_plays_only_once_per_inference() -> None:
    tts = _MockTts()
    handler = HoldMessageHandler(
        messages=["Hold on."],
        timeout_seconds=0.05,
        tts=tts,
    )

    with patch(
        "apps.runtime.services.pipecat.hold.random.choice",
        return_value="Hold on.",
    ):
        await handler.on_inference_started()
        await asyncio.sleep(0.1)
        await asyncio.sleep(0.1)

    assert tts.queue_frame.await_count == 1


@pytest.mark.asyncio
async def test_hold_uses_random_choice() -> None:
    tts = _MockTts()
    handler = HoldMessageHandler(
        messages=["First", "Second"],
        timeout_seconds=0.05,
        tts=tts,
    )

    with patch(
        "apps.runtime.services.pipecat.hold.random.choice",
        return_value="Second",
    ) as mock_choice:
        await handler.on_inference_started()
        await asyncio.sleep(0.1)

    mock_choice.assert_called_once_with(["First", "Second"])
    frame = tts.queue_frame.await_args.args[0]
    assert isinstance(frame, TTSSpeakFrame)
    assert frame.text == "Second"
