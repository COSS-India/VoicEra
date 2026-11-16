"""Hold timer orchestration: one random clip per slow LLM turn."""

from __future__ import annotations

import asyncio
import random
from typing import Any

from loguru import logger
from pipecat.frames.frames import TextFrame

from apps.runtime.services.pipecat.hold.audio_loader import preload_audio_clips
from apps.runtime.services.pipecat.hold.clips import (
    AudioHoldClip,
    HoldClip,
    HoldConfig,
    TextHoldClip,
    hold_config_from_behaviour,
)
from apps.runtime.services.pipecat.hold.players import HoldPlayer, player_for_mode


class HoldMessageHandler:
    """Play a single hold clip if the LLM has not responded within a timeout."""

    def __init__(
        self,
        *,
        clips: tuple[HoldClip, ...],
        timeout_seconds: float,
        player: HoldPlayer,
        mode: str,
        org_id: str | None = None,
        sample_rate: int | None = None,
        fetch_bytes: Any | None = None,
    ) -> None:
        self._clips = clips
        self._timeout_seconds = timeout_seconds
        self._player = player
        self._mode = mode
        self._org_id = org_id
        self._sample_rate = sample_rate
        self._fetch_bytes = fetch_bytes
        self._task: asyncio.Task[None] | None = None
        self._cancelled = False
        self._prepared = mode != "audio"
        self._enabled = True

    @property
    def is_active(self) -> bool:
        """True when the handler has playable clips after prepare()."""
        return self._enabled and bool(self._clips)

    # Back-compat for existing unit tests that inspect message strings.
    @property
    def _messages(self) -> list[str]:
        return [c.text for c in self._clips if isinstance(c, TextHoldClip)]

    async def prepare(self) -> None:
        """Preload audio clips when in audio mode. May disable the handler."""
        if self._mode != "audio":
            self._prepared = True
            return
        if self._org_id is None or not self._sample_rate:
            logger.warning("Hold audio mode missing org_id/sample_rate; disabling")
            self._clips = ()
            self._enabled = False
            self._prepared = True
            return

        audio_clips = tuple(
            c for c in self._clips if isinstance(c, AudioHoldClip)
        )
        loaded = await preload_audio_clips(
            audio_clips,
            org_id=self._org_id,
            sample_rate=self._sample_rate,
            fetch_bytes=self._fetch_bytes,
        )
        self._clips = loaded
        self._prepared = True
        if not self._clips:
            logger.warning("No hold audio clips could be prepared; disabling hold")
            self._enabled = False

    async def on_inference_started(self) -> None:
        if not self._enabled or not self._clips:
            return
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
        if self._cancelled or not self._enabled or not self._clips:
            return
        clip = random.choice(self._clips)
        logger.info(
            "Playing hold {} clip after {:.2f}s wait",
            self._mode,
            self._timeout_seconds,
        )
        await self._player.play(clip)


def hold_from_behaviour(
    behaviour: dict[str, Any],
    tts: Any,
    *,
    sample_rate: int | None = None,
    org_id: str | None = None,
    fetch_bytes: Any | None = None,
) -> HoldMessageHandler | None:
    config: HoldConfig | None = hold_config_from_behaviour(behaviour)
    if config is None:
        return None

    return HoldMessageHandler(
        clips=config.clips,
        timeout_seconds=config.timeout_seconds,
        player=player_for_mode(config.mode, tts),
        mode=config.mode,
        org_id=org_id,
        sample_rate=sample_rate,
        fetch_bytes=fetch_bytes,
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

    llm_processors = getattr(llm, "services", None) or [llm]

    def _register_llm_cancel(processor: Any) -> None:
        @processor.event_handler("on_after_push_frame")
        async def on_llm_after_push_frame(_processor: Any, frame: Any) -> None:
            if isinstance(frame, TextFrame):
                await hold_handler.cancel()

    for llm_processor in llm_processors:
        _register_llm_cancel(llm_processor)
