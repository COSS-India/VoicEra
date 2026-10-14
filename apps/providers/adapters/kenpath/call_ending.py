"""End Kenpath calls when the LLM signals goodbye or end of interaction."""

from __future__ import annotations

import re

from loguru import logger
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    EndWorkerFrame,
    Frame,
    InterruptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService

_GOODBYE = re.compile(r"\bgoodbye\b", re.IGNORECASE)


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
    """Defer hangup until ``BotStoppedSpeakingFrame``; cancel on ``InterruptionFrame``."""

    _hangup_pending: bool
    _kenpath_had_tts: bool

    def _kenpath_init_call_ending(self) -> None:
        self._hangup_pending = False
        self._kenpath_had_tts = False

    async def _kenpath_on_call_ending_frame(self, frame: Frame) -> None:
        if isinstance(frame, InterruptionFrame):
            if self._hangup_pending:
                logger.info("Kenpath end-of-call cancelled — user interrupted farewell")
            self._hangup_pending = False
        elif isinstance(frame, BotStoppedSpeakingFrame) and self._hangup_pending:
            self._hangup_pending = False
            logger.info(
                "Kenpath deferred end — farewell playback complete, pushing EndWorkerFrame"
            )
            await end_call(self)

    async def _kenpath_finish_turn_if_end(self, *, end_requested: bool) -> None:
        if not end_requested:
            return
        if self._kenpath_had_tts:
            self._hangup_pending = True
            logger.info("Kenpath end-of-call deferred until bot stops speaking")
        else:
            await end_call(self)
