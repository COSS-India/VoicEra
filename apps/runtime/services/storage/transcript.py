"""Buffer Pipecat turn transcripts and upload to MinIO at call end.

Objects are stored at ``voicera-calls/{org_id}/{call_id}/transcript.txt``.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    UserTurnStoppedMessage,
)

from apps.runtime.services.privacy.audio import TurnTiming, timings_for_turns
from apps.runtime.services.privacy.redaction import (
    enabled_entities,
    is_enabled,
    redact_live_if_enabled,
    redact_turns_with_spans,
)
from apps.runtime.services.storage.call_artifacts import save_and_link
from apps.runtime.services.storage.object_storage import minio_uri


class TranscriptWriter:
    """Buffer transcript lines in memory and upload once when the call ends.

    Lines are redacted when the transcript is rendered, not as they arrive, so
    redaction can use the whole call: a phone number split over two turns, or the
    last eight digits of a number given in full earlier. Raw text stays in this
    process's memory only, as it already does in the LLM context, and is dropped
    as soon as the transcript is rendered.

    After ``flush``, ``turn_timings`` says when each turn happened and what was
    redacted in it, so the call recording can mute the same parts.
    """

    def __init__(self, *, org_id: str, call_id: str) -> None:
        self._org_id = org_id
        self._call_id = call_id
        # (role, turn start timestamp, content, turn end in epoch seconds)
        self._lines: list[tuple[str, str, str, float]] = []
        self._flushed = False
        self.turn_timings: list[TurnTiming] = []

    @property
    def object_uri(self) -> str:
        return minio_uri(self._org_id, self._call_id, "transcript.txt")

    def append(self, role: str, timestamp: str, content: str) -> None:
        self._lines.append((role, timestamp, content, time.time()))

    def render(self) -> str:
        """The transcript as it is stored, redacted when PII redaction is enabled."""
        contents = [content for _, _, content, _ in self._lines]
        self.turn_timings = []
        if is_enabled():
            try:
                redacted = redact_turns_with_spans(
                    [(role, content) for role, _, content, _ in self._lines], enabled_entities()
                )
                contents = [text for text, _ in redacted]
                self.turn_timings = timings_for_turns(
                    [(role, ts, end, content) for role, ts, content, end in self._lines], redacted
                )
            except Exception:  # noqa: BLE001
                # Never store raw text because the call-level pass failed: fall back
                # to the stricter per-line redaction, and mute every turn.
                logger.exception("Call-level PII redaction failed call_id={}", self._call_id)
                contents = [redact_live_if_enabled(content) for content in contents]
                self.turn_timings = [
                    TurnTiming(role, None, end, content, ((0, len(content)),))
                    for role, _, content, end in self._lines
                ]
        body = "".join(
            f"[{timestamp}] {role}: {content}\n"
            for (role, timestamp, _, _), content in zip(self._lines, contents)
        )
        return f"call_id={self._call_id}\n---\n{body}"

    async def flush(self) -> None:
        """Upload the transcript and link it on the CallLog (once per call)."""
        if self._flushed or not self._lines:
            return

        self._flushed = True
        data = self.render().encode("utf-8")
        self._lines.clear()
        await save_and_link(
            org_id=self._org_id,
            call_id=self._call_id,
            filename="transcript.txt",
            data=data,
            content_type="text/plain",
            url_field="transcript_url",
        )


def register_transcript_file_logging(
    user_aggregator: Any,
    assistant_aggregator: Any,
    *,
    org_id: str,
    call_id: str,
) -> TranscriptWriter:
    """Register turn handlers that buffer transcript lines until ``flush()``."""
    writer = TranscriptWriter(org_id=org_id, call_id=call_id)

    @user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped(
        aggregator: Any,
        strategy: Any,
        message: UserTurnStoppedMessage,
    ) -> None:
        writer.append("user", message.timestamp, message.content)

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn_stopped(
        aggregator: Any,
        message: AssistantTurnStoppedMessage,
    ) -> None:
        if message.content:
            writer.append("assistant", message.timestamp, message.content)

    logger.info("Transcript buffering enabled uri={}", writer.object_uri)
    return writer
