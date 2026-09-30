"""End Kenpath calls when the LLM signals goodbye or end of interaction."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    EndWorkerFrame,
    Frame,
    InterruptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import LLMService

# Kenpath sends only the word "goodbye" as the hangup signal.
_GOODBYE = re.compile(r"\bgoodbye\b", re.IGNORECASE)


def response_requests_end_call(text: str) -> bool:
    """Return True when LLM text contains the Kenpath hangup word ``goodbye``."""
    return bool(_GOODBYE.search(text or ""))


def strip_goodbye_for_tts(text: str) -> str:
    """Remove ``goodbye`` so TTS never speaks the hangup signal."""
    if not text:
        return ""
    # Keep a trailing space when the chunk was a streamed word separator.
    trailing_space = text.endswith(" ")
    stripped = _GOODBYE.sub("", text)
    stripped = " ".join(stripped.split())
    if stripped and trailing_space:
        return stripped + " "
    return stripped


class KenpathCallEndingController:
    """Defer Kenpath hangup until farewell audio finishes, unless interrupted."""

    def __init__(self) -> None:
        self._pending_hangup = False
        self._cancelled = False

    def request_end_after_playback(self) -> None:
        self._pending_hangup = True
        self._cancelled = False
        logger.info("Kenpath end-of-call deferred until bot stops speaking")

    def cancel_pending_end(self) -> None:
        if self._pending_hangup:
            logger.info("Kenpath end-of-call cancelled — user interrupted farewell")
        self._pending_hangup = False
        self._cancelled = True

    def should_end_on_bot_stopped(self) -> bool:
        if self._pending_hangup and not self._cancelled:
            self._pending_hangup = False
            self._cancelled = False
            return True
        self._pending_hangup = False
        self._cancelled = False
        return False


class KenpathDeferredCallEndingProcessor(FrameProcessor):
    """End the call after farewell playback unless the user interrupts."""

    def __init__(self, controller: KenpathCallEndingController, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._controller = controller

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            self._controller.cancel_pending_end()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            if self._controller.should_end_on_bot_stopped():
                logger.info(
                    "Kenpath deferred end — farewell playback complete, pushing EndWorkerFrame"
                )
                await self.push_frame(EndWorkerFrame(), FrameDirection.DOWNSTREAM)

        await self.push_frame(frame, direction)


async def end_call(llm: LLMService) -> None:
    """Push EndWorkerFrame so the pipeline drains and the call ends."""
    logger.info("Kenpath end-of-call signal — pushing EndWorkerFrame")
    await llm.push_frame(EndWorkerFrame(), FrameDirection.DOWNSTREAM)


async def schedule_end_call(
    llm: LLMService,
    controller: KenpathCallEndingController | None,
    *,
    had_spoken_output: bool,
) -> None:
    """End immediately when there is nothing to play; otherwise defer until playback."""
    if not had_spoken_output or controller is None:
        await end_call(llm)
        return
    controller.request_end_after_playback()


class KenpathCallEndingMixin:
    """Kenpath LLM hook: deferred hangup processor inserted after transport output."""

    def _init_call_ending(self) -> None:
        self._response_had_spoken_output = False
        self._call_ending_controller = KenpathCallEndingController()
        self._call_ending_processor = KenpathDeferredCallEndingProcessor(
            self._call_ending_controller
        )

    def set_call_ending_controller(
        self, controller: KenpathCallEndingController
    ) -> None:
        """Replace the controller, mainly for unit tests."""
        self._call_ending_controller = controller
        self._call_ending_processor = KenpathDeferredCallEndingProcessor(controller)

    def pipeline_processors_after_output(self) -> list[FrameProcessor]:
        return [self._call_ending_processor]
