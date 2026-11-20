"""Raya-compatible post-call webhook body (``config.webhook.format = "raya"``).

Blue Dots' receiver was built for Raya's webhook. Fields, types and values
follow Raya's docs (docs.litwizlabs.com, "Webhooks" in Core Concepts):

    uuid, caller_no, to_number, in_did, out_did, call_transcript,
    call_recording_url, outcome ("Completed" | "Failure"), call_start_time,
    call_end_time, call_duration (seconds), agent_id, agent_args, timezone,
    call_output, created_at, batch_id, contact_id

Times are ISO 8601 UTC with a ``Z``. ``in_did`` / ``out_did`` are numbers or
null. The call_transcript turn shape is not in Raya's docs; ``raya_transcript``
holds it in one place until Blue Dots shares a real body.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_MAX_RETRY_DEPTH = 20


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _did(value: Any) -> int | None:
    digits = _digits(value)
    return int(digits) if digits else None


def _iso_z(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    text = moment.isoformat(timespec="milliseconds" if moment.microsecond else "seconds")
    return text.replace("+00:00", "Z")


def _duration(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def raya_transcript(turns: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """PROVISIONAL turn shape: Raya documents only "array of conversation messages"."""
    return [
        {
            "role": "assistant" if turn.get("speaker") == "agent" else "user",
            "content": turn.get("text") or "",
            "timestamp": turn.get("timestamp"),
        }
        for turn in (turns or [])
    ]


def contact_id_for(call_doc: dict[str, Any], db: Any) -> str | None:
    """The campaign contact: the root of the call's queued-run retry chain."""
    run_id = call_doc.get("queued_run_id")
    if not run_id or db is None:
        return None
    runs = db["QueuedRuns"]
    current = str(run_id)
    for _ in range(_MAX_RETRY_DEPTH):
        run = runs.find_one({"queued_run_id": current}, {"parent_queued_run_id": 1})
        parent = (run or {}).get("parent_queued_run_id")
        if not parent:
            return current
        current = str(parent)
    return current


def build_raya_payload(
    call_doc: dict[str, Any],
    *,
    transcript: list[dict[str, Any]] | None,
    recording_url: str | None,
    contact_id: str | None,
) -> dict[str, Any]:
    answered = call_doc.get("call_response") == "answered"
    call_type = call_doc.get("call_type")
    return {
        "uuid": call_doc.get("call_id"),
        "caller_no": _digits(call_doc.get("from_number")) or None,
        "to_number": _digits(call_doc.get("to_number")) or None,
        "in_did": _did(call_doc.get("to_number")) if call_type == "inbound" else None,
        "out_did": _did(call_doc.get("from_number")) if call_type == "outbound" else None,
        "call_transcript": raya_transcript(transcript) if answered else [],
        "call_recording_url": (recording_url or "") if answered else "",
        "outcome": "Completed" if answered else "Failure",
        "call_start_time": _iso_z(call_doc.get("start_time_utc")),
        "call_end_time": _iso_z(call_doc.get("end_time_utc")),
        "call_duration": _duration(call_doc.get("duration")),
        "agent_id": call_doc.get("agent_id"),
        "agent_args": dict(call_doc.get("custom_variables") or {}),
        "timezone": "UTC",
        "call_output": (call_doc.get("call_output") or {}) if answered else {},
        "created_at": _iso_z(call_doc.get("created_at")),
        "batch_id": call_doc.get("campaign_id"),
        "contact_id": contact_id,
    }
