"""Redact the live transcript the browser test panel receives over RTVI.

The panel builds its conversation from two RTVI events only (client-react 1.8):
``user-transcription`` for the caller and ``bot-output`` for the agent, including
the spoken / not-yet-spoken split. Both carry whole utterances or sentences, so
they can be redacted message by message.

``bot-llm-text``, ``bot-tts-text`` and ``bot-transcription`` stream the agent's
text a token or a word at a time. A number split across chunks cannot be
redacted reliably, and the panel does not use them, so they are not sent while
redaction is on.

Every RTVI message, from the observer and from the processor itself, goes out
through ``RTVIProcessor.push_transport_message``, so that is the one place this
hooks into.
"""

from __future__ import annotations

from typing import Any

from pipecat.frames.frames import OutputTransportMessageUrgentFrame
from pipecat.processors.frameworks.rtvi import RTVIProcessor
from pydantic import BaseModel

from apps.runtime.services.privacy.redaction import (
    is_enabled,
    redact_live_if_enabled,
    redact_progress_if_enabled,
)

# Streamed a token or a word at a time; unused by the panel.
_STREAMED = frozenset({"bot-llm-text", "bot-tts-text", "bot-transcription"})
# Whole utterances or sentences with the text in ``data.text``.
_WHOLE = frozenset({"user-transcription", "user-llm-text"})


def redact_rtvi_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Return the message with its text redacted, or ``None`` to drop it."""
    if not is_enabled():
        return message
    kind = message.get("type")
    if kind in _STREAMED:
        return None
    data = message.get("data")
    if not isinstance(data, dict):
        return message
    if kind in _WHOLE and isinstance(data.get("text"), str):
        data["text"] = redact_live_if_enabled(data["text"])
    elif kind == "bot-output" and isinstance(data.get("text"), str):
        progress = data.get("spoken_progress")
        if isinstance(progress, dict):
            text, spoken, unspoken = redact_progress_if_enabled(
                data["text"],
                str(progress.get("accumulated_text") or ""),
                str(progress.get("remaining_text") or ""),
            )
            data["text"] = text
            if "accumulated_text" in progress:
                progress["accumulated_text"] = spoken
            if "remaining_text" in progress:
                progress["remaining_text"] = unspoken
        else:
            data["text"] = redact_live_if_enabled(data["text"])
    return message


class RedactingRTVIProcessor(RTVIProcessor):
    """``RTVIProcessor`` that redacts transcript text before it leaves the runtime."""

    async def push_transport_message(self, model: BaseModel, exclude_none: bool = True):
        message = redact_rtvi_message(model.model_dump(exclude_none=exclude_none))
        if message is None:
            return
        await self.push_frame(OutputTransportMessageUrgentFrame(message=message))
