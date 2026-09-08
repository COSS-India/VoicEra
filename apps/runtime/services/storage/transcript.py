"""Buffer Pipecat turn transcripts and upload to MinIO at call end.

Objects are stored at ``voicera-calls/{org_id}/{call_id}/transcript.txt``.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    UserTurnStoppedMessage,
)

from apps.runtime.services.storage.call_artifacts import save_and_link
from apps.runtime.services.storage.object_storage import minio_uri


class TranscriptWriter:
    """Buffer transcript lines in memory and upload once when the call ends."""

    def __init__(self, *, org_id: str, call_id: str) -> None:
        self._org_id = org_id
        self._call_id = call_id
        self._buffer = f"call_id={call_id}\n---\n"
        self._has_content = False
        self._flushed = False

    @property
    def object_uri(self) -> str:
        return minio_uri(self._org_id, self._call_id, "transcript.txt")

    def append(self, role: str, timestamp: str, content: str) -> None:
        self._buffer += f"[{timestamp}] {role}: {content}\n"
        self._has_content = True

    async def flush(self) -> None:
        """Upload the transcript and link it on the CallLog (once per call)."""
        if self._flushed or not self._has_content:
            return

        self._flushed = True
        await save_and_link(
            org_id=self._org_id,
            call_id=self._call_id,
            filename="transcript.txt",
            data=self._buffer.encode("utf-8"),
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
