"""Vendor-agnostic telephony webhook form parsing (Vobiz / Plivo)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import parse_qs

_HANGUP_EVENTS = frozenset({"hangup", "hangupcomplete", "callhangup"})


def _get_nested(payload: Mapping[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def resolve_provider_call_sid(payload: Mapping[str, Any]) -> str | None:
    """Resolve canonical provider call identifier from webhook or WS payload."""
    candidate_paths = (
        ("CallUUID",),
        ("call_uuid",),
        ("call_id",),
        ("callId",),
        ("callSid",),
        ("CallSid",),
        ("request_uuid",),
        ("start", "callId"),
        ("start", "callSid"),
        ("start", "call_uuid"),
    )
    for path in candidate_paths:
        value = _get_nested(payload, *path)
        if value:
            resolved = str(value).strip()
            if resolved:
                return resolved
    return None


def _first_str(payload: Mapping[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


@dataclass(frozen=True)
class TelephonyWebhookEvent:
    """Normalized telephony webhook fields."""

    event: str
    from_number: str
    to_number: str
    direction: str
    provider_call_sid: str | None
    hangup_cause: str
    call_status: str


def parse_stream_start(start_info: Mapping[str, Any]) -> dict[str, str | None]:
    """Extract call identifiers and numbers from a WebSocket ``start`` object."""
    payload = dict(start_info)
    return {
        "provider_call_sid": resolve_provider_call_sid(payload),
        "from_number": _first_str(payload, "from", "From", default="unknown"),
        "to_number": _first_str(payload, "to", "To", default="unknown"),
    }


def decode_webhook_body(raw: bytes) -> dict[str, Any]:
    """Parse a telephony webhook body as JSON or ``x-www-form-urlencoded``.

    Vobiz/Plivo answer callbacks may be either encoding. ``request.form()``
    only reads form types, so JSON ``From`` / ``To`` / ``CallUUID`` would
    otherwise be dropped.
    """
    if not raw:
        return {}
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    if text[0] in "{[":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    pairs = parse_qs(text, keep_blank_values=False)
    return {key: values[0] for key, values in pairs.items() if values}


def merge_webhook_payload(
    form_dict: Mapping[str, Any],
    query_params: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Merge query params into form data (Vobiz may send CallUUID on the URL)."""
    merged = dict(form_dict)
    if not query_params:
        return merged
    for key, value in query_params.items():
        if value and key not in merged:
            merged[key] = value
    return merged


def parse_webhook_form(form_dict: Mapping[str, Any]) -> TelephonyWebhookEvent:
    """Parse provider POST form data into normalized call fields."""
    event = _first_str(form_dict, "Event", "event")
    from_number = _first_str(form_dict, "From", "from", default="unknown")
    to_number = _first_str(form_dict, "To", "to", default="unknown")
    direction = _first_str(form_dict, "Direction", "direction", default="inbound").lower()
    hangup_cause = _first_str(form_dict, "HangupCause", "hangup_cause")
    call_status = _first_str(form_dict, "CallStatus", "call_status").lower()
    provider_call_sid = resolve_provider_call_sid(form_dict)
    return TelephonyWebhookEvent(
        event=event,
        from_number=from_number,
        to_number=to_number,
        direction=direction,
        provider_call_sid=provider_call_sid,
        hangup_cause=hangup_cause,
        call_status=call_status,
    )


def is_hangup_event(event: str | None) -> bool:
    """Return True when the webhook event indicates call hangup."""
    if not event:
        return False
    normalized = str(event).strip().lower()
    if normalized in _HANGUP_EVENTS:
        return True
    return "hangup" in normalized


def map_hangup_call_response(call_status: str, hangup_cause: str = "") -> str | None:
    """Map provider hangup fields to a terminal ``call_response``, if known."""
    status = (call_status or "").strip().lower().replace("_", "-")
    if status == "busy":
        return "busy"
    if status in {"no-answer", "noanswer"}:
        return "no_answer"
    if status == "failed":
        return "failed"
    if status in {"cancelled", "canceled"}:
        return "cancelled"

    cause = (hangup_cause or "").strip().upper()
    if cause in {"USER_BUSY", "BUSY"}:
        return "busy"
    if cause in {"NO_ANSWER", "ORIGINATOR_CANCEL", "CALL_REJECTED", "UNALLOCATED_NUMBER"}:
        return "no_answer"
    return None
