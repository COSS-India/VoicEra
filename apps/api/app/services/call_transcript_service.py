"""Turn-by-turn transcripts parsed from the runtime's transcript file.

The runtime (``apps/runtime/services/storage/transcript.py``) writes one
``transcript.txt`` per call to MinIO::

    call_id=<id>
    ---
    [<timestamp>] user: <text>
    [<timestamp>] assistant: <text>

A turn whose text spans several lines continues on lines with no
``[timestamp] role:`` prefix. Parsing on read (rather than changing the
runtime's format) means calls recorded before this change get turns too.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.storage.minio_client import MinIOStorage

logger = logging.getLogger(__name__)

_LINE = re.compile(r"^\[(?P<timestamp>[^\]]*)\] (?P<role>user|assistant): ?(?P<text>.*)$")
_SPEAKER = {"user": "caller", "assistant": "agent"}


def _new_storage() -> MinIOStorage:
    return MinIOStorage()


class TranscriptUnavailableError(Exception):
    """The call has no transcript yet, or it could not be read."""

    def __init__(self, call_id: str, reason: str) -> None:
        self.call_id = call_id
        self.reason = reason
        super().__init__(f"Transcript unavailable for call {call_id}: {reason}")


def parse_transcript(text: str) -> list[dict[str, Any]]:
    """Turn the runtime's transcript text into ordered turns."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    # Skip the "call_id=…" header, which ends at the first "---" line.
    if "---" in lines[:5]:
        lines = lines[lines.index("---") + 1 :]

    turns: list[dict[str, Any]] = []
    for line in lines:
        match = _LINE.match(line)
        if match:
            role = match.group("role")
            turns.append(
                {
                    "index": len(turns),
                    "role": role,
                    "speaker": _SPEAKER[role],
                    "timestamp": match.group("timestamp") or None,
                    "text": match.group("text"),
                }
            )
        elif turns:
            turns[-1]["text"] += "\n" + line
    for turn in turns:
        turn["text"] = turn["text"].rstrip("\n")
    return turns


def read_transcript_text(call_doc: dict[str, Any], *, storage: MinIOStorage | None = None) -> str:
    call_id = str(call_doc.get("call_id") or "")
    url = call_doc.get("transcript_url")
    if not url:
        raise TranscriptUnavailableError(call_id, "no transcript on this call yet")
    parsed = MinIOStorage.parse_minio_url(str(url))
    if not parsed:
        raise TranscriptUnavailableError(call_id, "invalid transcript URL on call log")
    bucket_name, object_name = parsed
    client = (storage or _new_storage()).client
    try:
        response = client.get_object(bucket_name, object_name)
    except Exception as exc:
        raise TranscriptUnavailableError(call_id, f"could not read transcript: {exc}") from exc
    try:
        return response.read().decode("utf-8", errors="replace")
    finally:
        response.close()
        response.release_conn()


def load_turns(call_doc: dict[str, Any], *, storage: MinIOStorage | None = None) -> list[dict[str, Any]]:
    """Read and parse a call's transcript. Raises TranscriptUnavailableError."""
    return parse_transcript(read_transcript_text(call_doc, storage=storage))


def try_load_turns(call_doc: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Like :func:`load_turns` but returns None instead of raising."""
    try:
        return load_turns(call_doc)
    except TranscriptUnavailableError as exc:
        logger.info("%s", exc)
    except Exception:
        logger.exception("Unexpected error loading transcript call_id=%s", call_doc.get("call_id"))
    return None
