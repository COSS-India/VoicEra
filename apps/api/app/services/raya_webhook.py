"""Raya-compatible post-call webhook body (``config.webhook.format = "raya"``).

Blue Dots' receiver was built for Raya's webhook. The body matches the real
Raya bodies Blue Dots shared (tests/sample_data/raya_webhook_*.json): the
same keys in the same order, the same types, and the same nulls.

* ``outcome`` is ``"Completed"`` (answered) or ``"Failure"``. On a Failure,
  ``call_transcript``, ``call_recording_url`` and ``call_output`` are null
  and ``call_duration`` is 0.
* Phone numbers are E.164 with a ``+``; ``in_did`` / ``out_did`` are numbers.
  ``caller_no`` is null on outbound calls.
* Times are ISO 8601 UTC with milliseconds and a ``Z``. ``timezone`` is null.
* ``call_transcript`` is an OpenAI-style message list: the agent's system
  prompt, the spoken turns as ``{role, content}``, and each tool call as an
  assistant ``tool_calls`` message followed by a ``tool`` message with the
  result, in time order. Tool calls come from AI DPG's logs (see
  ``call_output.bluedots.signals``) and keep AI DPG's tool names; a result
  that is a JSON object is written as a Python dict string, as Raya does.

Raya's docs also list ``batch_id`` and ``contact_id``; real bodies do not
carry them, so neither do we.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

RAYA_FIELDS = (
    "uuid",
    "caller_no",
    "to_number",
    "in_did",
    "out_did",
    "call_transcript",
    "call_recording_url",
    "enhanced_recording_url",
    "outcome",
    "call_start_time",
    "call_end_time",
    "call_duration",
    "agent_id",
    "agent_args",
    "timezone",
    "call_output",
    "created_at",
)


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _e164(value: Any) -> str | None:
    digits = _digits(value)
    return f"+{digits}" if digits else None


def _did(value: Any) -> int | None:
    digits = _digits(value)
    return int(digits) if digits else None


def _moment(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso_ms(value: Any) -> str | None:
    """``2026-11-20T14:40:42.670Z``: UTC, always milliseconds, as Raya sends."""
    moment = _moment(value)
    if moment is None:
        return None
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _duration(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _ts_ns(value: Any) -> int | None:
    moment = _moment(value)
    return int(moment.timestamp() * 1_000_000_000) if moment else None


def _tool_result(result: Any, error: Any) -> str:
    if result is None:
        return str(error or "")
    try:
        parsed = json.loads(result)
    except (TypeError, ValueError):
        return str(result)  # cut off by AI DPG, or not JSON: as logged
    return repr(parsed) if isinstance(parsed, (dict, list)) else str(result)


def _tool_messages(call: dict[str, Any]) -> list[dict[str, Any]]:
    trace = str(call.get("trace_id") or "") or format(int(call.get("ts_ns") or 0), "x")
    call_id = f"call_{trace}"
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": str(call.get("tool") or ""),
                        "arguments": json.dumps(call.get("arguments") or {}, ensure_ascii=False),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "content": _tool_result(call.get("result"), call.get("error")),
            "tool_call_id": call_id,
        },
    ]


def raya_transcript(
    turns: list[dict[str, Any]] | None,
    *,
    system_prompt: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Raya's message list: system prompt, then turns and tool calls by time."""
    timeline: list[tuple[int, int, list[dict[str, Any]]]] = []
    last = 0
    for order, turn in enumerate(turns or []):
        # A turn without a timestamp stays right after the previous one.
        when = _ts_ns(turn.get("timestamp"))
        last = when if when is not None else last
        message = {
            "role": "assistant" if turn.get("speaker") == "agent" else "user",
            "content": turn.get("text") or "",
        }
        timeline.append((last, order, [message]))
    for order, call in enumerate(tool_calls or [], start=len(timeline)):
        timeline.append((int(call.get("ts_ns") or 0), order, _tool_messages(call)))
    timeline.sort(key=lambda item: (item[0], item[1]))

    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for _, _, chunk in timeline:
        messages.extend(chunk)
    return messages


def build_raya_payload(
    call_doc: dict[str, Any],
    *,
    transcript: list[dict[str, Any]] | None,
    recording_url: str | None,
    system_prompt: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    answered = call_doc.get("call_response") == "answered"
    inbound = call_doc.get("call_type") == "inbound"
    outbound = call_doc.get("call_type") == "outbound"
    call_output = call_doc.get("call_output")
    return {
        "uuid": call_doc.get("call_id"),
        "caller_no": _e164(call_doc.get("from_number")) if not outbound else None,
        "to_number": _e164(call_doc.get("to_number")),
        "in_did": _did(call_doc.get("to_number")) if inbound else None,
        "out_did": _did(call_doc.get("from_number")) if outbound else None,
        "call_transcript": (
            raya_transcript(transcript, system_prompt=system_prompt, tool_calls=tool_calls)
            if answered else None
        ),
        "call_recording_url": (recording_url or None) if answered else None,
        "enhanced_recording_url": None,
        "outcome": "Completed" if answered else "Failure",
        "call_start_time": _iso_ms(call_doc.get("start_time_utc")),
        "call_end_time": _iso_ms(call_doc.get("end_time_utc")),
        "call_duration": _duration(call_doc.get("duration")) if answered else 0,
        "agent_id": call_doc.get("agent_id"),
        "agent_args": dict(call_doc.get("custom_variables") or {}),
        "timezone": None,
        "call_output": (call_output or None) if answered and isinstance(call_output, dict) else None,
        "created_at": _iso_ms(call_doc.get("created_at")),
    }
