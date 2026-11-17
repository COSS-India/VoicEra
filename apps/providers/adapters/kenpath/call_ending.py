"""End Kenpath calls when the LLM signals goodbye or end of interaction."""

from __future__ import annotations

import asyncio
import re

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndWorkerFrame,
    Frame,
    InterruptionFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService

_GOODBYE = re.compile(r"\bgoodbye\b", re.IGNORECASE)
# TTS may emit bot-stopped between segments; wait for a quiet gap before hangup.
_FAREWELL_HANGUP_DEBOUNCE_SECS = 1.5


def response_requests_end_call(text: str) -> bool:
    return bool(_GOODBYE.search(text or ""))


def strip_goodbye_for_tts(text: str) -> str:
    if not text:
        return ""
    trailing_space = text.endswith(" ")
    stripped = _GOODBYE.sub("", text)
    stripped = " ".join(stripped.split())
    if stripped and trailing_space:
        return stripped + " "
    return stripped


async def end_call(llm: LLMService) -> None:
    logger.info("Kenpath end-of-call signal — pushing EndWorkerFrame")
    await llm.push_frame(EndWorkerFrame(), FrameDirection.DOWNSTREAM)


class KenpathCallEndingMixin:
    """Defer hangup after farewell TTS; cancel if the user speaks during playback."""

    _hangup_pending: bool
    _kenpath_had_tts: bool
    _kenpath_bot_speaking: bool
    _kenpath_farewell_user_barged: bool
    _kenpath_hangup_timer_task: asyncio.Task[None] | None

    def _kenpath_init_call_ending(self) -> None:
        self._hangup_pending = False
        self._kenpath_had_tts = False
        self._kenpath_bot_speaking = False
        self._kenpath_farewell_user_barged = False
        self._kenpath_hangup_timer_task = None

    def _kenpath_begin_assistant_turn(self) -> None:
        self._kenpath_had_tts = False
        self._kenpath_farewell_user_barged = False
        self._kenpath_cancel_hangup_timer()

    def _kenpath_cleanup_call_ending(self) -> None:
        self._kenpath_cancel_hangup_timer()

    def _kenpath_cancel_hangup_timer(self) -> None:
        task = self._kenpath_hangup_timer_task
        if task is not None and not task.done():
            task.cancel()
        self._kenpath_hangup_timer_task = None

    def _kenpath_cancel_farewell_hangup(self) -> None:
        self._kenpath_cancel_hangup_timer()
        if self._kenpath_bot_speaking:
            self._kenpath_farewell_user_barged = True
        if not self._hangup_pending:
            return
        logger.info("Kenpath end-of-call cancelled — user spoke during farewell")
        self._hangup_pending = False

    def _kenpath_schedule_hangup_after_quiet(self) -> None:
        self._kenpath_cancel_hangup_timer()
        self._kenpath_hangup_timer_task = asyncio.create_task(
            self._kenpath_hangup_after_debounce(),
        )

    async def _kenpath_hangup_after_debounce(self) -> None:
        try:
            await asyncio.sleep(_FAREWELL_HANGUP_DEBOUNCE_SECS)
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            return
        finally:
            self._kenpath_hangup_timer_task = None
        if (
            not self._hangup_pending
            or self._kenpath_farewell_user_barged
            or self._kenpath_bot_speaking
        ):
            return
        self._hangup_pending = False
        logger.info(
            "Kenpath deferred end — farewell playback complete, pushing EndWorkerFrame",
        )
        await end_call(self)

    async def _kenpath_on_call_ending_frame(self, frame: Frame) -> None:
        if isinstance(frame, InterruptionFrame):
            self._kenpath_cancel_farewell_hangup()
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._kenpath_cancel_farewell_hangup()
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._kenpath_bot_speaking = True
            self._kenpath_cancel_hangup_timer()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._kenpath_bot_speaking = False
            if not self._hangup_pending or self._kenpath_farewell_user_barged:
                return
            await asyncio.sleep(0)
            if not self._hangup_pending or self._kenpath_farewell_user_barged:
                return
            self._kenpath_schedule_hangup_after_quiet()

    async def _kenpath_finish_turn_if_end(self, *, end_requested: bool) -> None:
        if not end_requested:
            return
        if self._kenpath_farewell_user_barged:
            return
        if self._kenpath_had_tts:
            self._hangup_pending = True
            logger.info("Kenpath end-of-call deferred until bot stops speaking")
        else:
            await end_call(self)
