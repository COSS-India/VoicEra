"""One-shot hold/filler messages while waiting for LLM responses."""

from __future__ import annotations

import asyncio
import random
from typing import Any

from loguru import logger
from pipecat.frames.frames import TextFrame, TTSSpeakFrame


class HoldMessageHandler:
    """Play a single hold message if the LLM has not responded within a timeout."""

    def __init__(
        self,
        messages: list[str],
        timeout_seconds: float,
        tts: Any,
    ) -> None:
        self._messages = messages
        self._timeout_seconds = timeout_seconds
        self._tts = tts
        self._task: asyncio.Task[None] | None = None
        self._cancelled = False

    async def on_inference_started(self) -> None:
        await self.cancel()
        self._cancelled = False
        self._task = asyncio.create_task(self._wait_and_play())

    async def cancel(self) -> None:
        self._cancelled = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _wait_and_play(self) -> None:
        try:
            await asyncio.sleep(self._timeout_seconds)
        except asyncio.CancelledError:
            return
        if self._cancelled or not self._messages:
            return
        message = random.choice(self._messages)
        logger.info("Playing hold message after {:.2f}s wait", self._timeout_seconds)
        await self._tts.queue_frame(
            TTSSpeakFrame(message, append_to_context=False),
        )


def hold_from_behaviour(
    behaviour: dict[str, Any],
    tts: Any,
) -> HoldMessageHandler | None:
    raw_messages = behaviour.get("hold_messages") or []
    messages = [str(m).strip() for m in raw_messages if str(m).strip()]

    timeout_raw = behaviour.get("hold_message_timeout_seconds")
    if timeout_raw is None:
        return None
    timeout_seconds = float(timeout_raw)
    if timeout_seconds <= 0 or not messages:
        return None

    return HoldMessageHandler(
        messages=messages,
        timeout_seconds=timeout_seconds,
        tts=tts,
    )


def register_hold_handlers(
    user_aggregator: Any,
    llm: Any,
    hold_handler: HoldMessageHandler | None,
    *,
    idle_handler: Any | None = None,
) -> None:
    if idle_handler is not None or hold_handler is not None:

        @user_aggregator.event_handler("on_user_turn_started")
        async def on_user_turn_started(aggregator: Any, strategy: Any) -> None:
            if idle_handler is not None:
                idle_handler.reset()
            if hold_handler is not None:
                await hold_handler.cancel()

    if hold_handler is None:
        return

    @user_aggregator.event_handler("on_user_turn_inference_triggered")
    async def on_user_turn_inference_triggered(
        aggregator: Any, strategy: Any
    ) -> None:
        await hold_handler.on_inference_started()

    @llm.event_handler("on_after_push_frame")
    async def on_llm_after_push_frame(processor: Any, frame: Any) -> None:
        if isinstance(frame, TextFrame):
            await hold_handler.cancel()
