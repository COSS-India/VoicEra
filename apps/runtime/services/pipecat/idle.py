"""User online detection and idle handling for the Pipecat pipeline."""

from __future__ import annotations

from typing import Any

from pipecat.frames.frames import EndWorkerFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection


class UserOnlineDetectionHandler:
    """Play idle prompts then end the call after configured repeats."""

    def __init__(
        self,
        max_repeats: int,
        idle_message: str,
        closing_message: str,
    ) -> None:
        self._max_repeats = max(1, max_repeats)
        self._idle_message = idle_message
        self._closing_message = closing_message
        self._attempt = 0

    def reset(self) -> None:
        self._attempt = 0

    async def handle_idle(self, aggregator: Any) -> None:
        self._attempt += 1
        if self._attempt <= self._max_repeats:
            if self._idle_message:
                await aggregator.push_frame(TTSSpeakFrame(self._idle_message))
            return

        if self._closing_message:
            await aggregator.push_frame(TTSSpeakFrame(self._closing_message))
        await aggregator.push_frame(EndWorkerFrame(), FrameDirection.UPSTREAM)


def online_detection_from_behaviour(
    behaviour: dict[str, Any],
) -> tuple[bool, float, int, str, str, float]:
    enabled = bool(behaviour.get("user_online_detection_enabled"))
    seconds = float(behaviour.get("user_online_detection_seconds") or 10)
    repeats = int(behaviour.get("user_online_detection_repeats") or 1)
    idle_message = str(behaviour.get("user_online_detection_message") or "").strip()
    closing_message = str(
        behaviour.get("user_online_detection_closing_message") or ""
    ).strip()

    user_silence_hangup_seconds = float(behaviour.get("user_silence_hangup_seconds") or 0)
    return enabled, seconds, repeats, idle_message, closing_message, user_silence_hangup_seconds


def register_idle_handlers(
    user_aggregator: Any,
    *,
    online_detection_enabled: bool,
    idle_handler: UserOnlineDetectionHandler | None,
    closing_message: str,
) -> None:
    if online_detection_enabled:
        assert idle_handler is not None

        @user_aggregator.event_handler("on_user_turn_idle")
        async def on_user_turn_idle(aggregator: Any) -> None:
            await idle_handler.handle_idle(aggregator)
    else:

        @user_aggregator.event_handler("on_user_turn_idle")
        async def on_user_turn_idle(aggregator: Any) -> None:
            await aggregator.push_frame(TTSSpeakFrame(closing_message))
            await aggregator.push_frame(EndWorkerFrame(), FrameDirection.UPSTREAM)
