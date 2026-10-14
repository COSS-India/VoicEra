"""End Kenpath calls when the LLM signals goodbye or end of interaction."""

from __future__ import annotations

import re

from loguru import logger
from pipecat.frames.frames import EndWorkerFrame
from pipecat.processors.frame_processor import FrameDirection
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


async def end_call(llm: LLMService) -> None:
    """Push EndWorkerFrame so the pipeline drains and the call ends."""
    logger.info("Kenpath end-of-call signal — pushing EndWorkerFrame")
    await llm.push_frame(EndWorkerFrame(), FrameDirection.DOWNSTREAM)
