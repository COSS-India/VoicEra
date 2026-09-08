"""Telephony webhook parsing tests."""

from __future__ import annotations

from apps.telephony.webhooks import (
    decode_webhook_body,
    is_hangup_event,
    map_hangup_call_response,
    merge_webhook_payload,
    parse_stream_start,
    parse_webhook_form,
    resolve_provider_call_sid,
)


def test_resolve_provider_call_sid_vobiz_call_uuid() -> None:
    payload = {"CallUUID": "vobiz-uuid-1", "From": "+15551111111"}
    assert resolve_provider_call_sid(payload) == "vobiz-uuid-1"


def test_resolve_provider_call_sid_plivo_request_uuid() -> None:
    payload = {"CallSid": "plivo-sid-99", "request_uuid": "req-1"}
    assert resolve_provider_call_sid(payload) == "plivo-sid-99"


def test_resolve_provider_call_sid_nested_websocket_start() -> None:
    payload = {"start": {"callSid": "ws-call-1", "streamSid": "stream-1"}}
    assert resolve_provider_call_sid(payload) == "ws-call-1"


def test_parse_webhook_form_inbound_defaults() -> None:
    parsed = parse_webhook_form(
        {
            "Event": "StartApp",
            "From": "+15551234567",
            "To": "+15559876543",
            "Direction": "inbound",
            "CallUUID": "inbound-uuid",
        }
    )
    assert parsed.event == "StartApp"
    assert parsed.from_number == "+15551234567"
    assert parsed.to_number == "+15559876543"
    assert parsed.direction == "inbound"
    assert parsed.provider_call_sid == "inbound-uuid"


def test_parse_webhook_form_plivo_style_keys() -> None:
    parsed = parse_webhook_form(
        {
            "event": "answer",
            "from": "+15550001111",
            "to": "+15550002222",
            "CallSid": "plivo-call",
            "Direction": "outbound",
        }
    )
    assert parsed.event == "answer"
    assert parsed.from_number == "+15550001111"
    assert parsed.to_number == "+15550002222"
    assert parsed.provider_call_sid == "plivo-call"
    assert parsed.direction == "outbound"


def test_is_hangup_event() -> None:
    assert is_hangup_event("Hangup") is True
    assert is_hangup_event("hangup") is True
    assert is_hangup_event("CallHangup") is True
    assert is_hangup_event("StartApp") is False
    assert is_hangup_event(None) is False


def test_map_hangup_call_response() -> None:
    assert map_hangup_call_response("busy", "") == "busy"
    assert map_hangup_call_response("no-answer", "") == "no_answer"
    assert map_hangup_call_response("failed", "") == "failed"
    assert map_hangup_call_response("cancelled", "") == "cancelled"
    assert map_hangup_call_response("completed", "NO_ANSWER") == "no_answer"
    assert map_hangup_call_response("completed", "") is None


def test_merge_webhook_payload_query_params() -> None:
    merged = merge_webhook_payload(
        {"Event": "StartApp"},
        {"CallUUID": "url-uuid", "From": "+15551111111"},
    )
    parsed = parse_webhook_form(merged)
    assert parsed.provider_call_sid == "url-uuid"
    assert parsed.from_number == "+15551111111"


def test_parse_stream_start() -> None:
    meta = parse_stream_start(
        {
            "callSid": "ws-123",
            "streamSid": "stream-1",
            "from": "+15551234567",
            "to": "+15559876543",
        }
    )
    assert meta["provider_call_sid"] == "ws-123"
    assert meta["from_number"] == "+15551234567"
    assert meta["to_number"] == "+15559876543"


def test_decode_webhook_body_json() -> None:
    parsed = decode_webhook_body(
        b'{"Event":"StartApp","From":"+15551234567","To":"+15559876543","CallUUID":"uuid-1"}'
    )
    assert parse_webhook_form(parsed).from_number == "+15551234567"
    assert parse_webhook_form(parsed).provider_call_sid == "uuid-1"


def test_decode_webhook_body_form_urlencoded() -> None:
    parsed = decode_webhook_body(
        b"Event=StartApp&From=%2B15551234567&To=%2B15559876543&CallUUID=uuid-1"
    )
    assert parse_webhook_form(parsed).from_number == "+15551234567"
    assert parse_webhook_form(parsed).to_number == "+15559876543"
    assert parse_webhook_form(parsed).provider_call_sid == "uuid-1"
