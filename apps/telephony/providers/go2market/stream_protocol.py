"""Go To Market bi-directional streaming protocol constants (v2.0 guide)."""

from __future__ import annotations

from typing import Any, Mapping

from apps.telephony.providers.go2market.wire import (
    MULAW_FRAME_BYTES as MULAW_CHUNK_BYTES,
    MULAW_MAX_SEND_BYTES as MAX_MULAW_CHUNK_BYTES,
    WIRE_SAMPLE_RATE as GO2MARKET_SAMPLE_RATE,
)

# Events from go2market → partner
OUTBOUND_EVENTS = frozenset({"connected", "start", "media", "stop", "dtmf", "mark"})

# Events from partner → go2market
INBOUND_EVENTS = frozenset({"media", "mark", "clear"})


def normalize_start_message(message: Mapping[str, Any]) -> dict[str, Any]:
    """Merge top-level stream/call fields into nested ``start`` for downstream parsers.

    Some go2market deployments send ``streamSid`` / ``callSid`` only at the top level
    without a ``start`` object; others mirror top-level ``streamSid`` (guide §4.2).
    """
    out = dict(message)
    start = out.get("start")
    merged = dict(start) if isinstance(start, dict) else {}

    for top_key, dest_key in (
        ("streamSid", "streamSid"),
        ("stream_sid", "streamSid"),
        ("streamId", "streamSid"),
        ("callSid", "callSid"),
        ("callId", "callSid"),
        ("call_uuid", "callSid"),
        ("CallUUID", "callSid"),
        ("from", "from"),
        ("to", "to"),
        ("direction", "direction"),
    ):
        top_val = out.get(top_key)
        if top_val and not merged.get(dest_key):
            merged[dest_key] = top_val

    out["start"] = merged
    if merged.get("streamSid") and not out.get("streamSid"):
        out["streamSid"] = merged["streamSid"]
    return out


def resolve_stream_sid(message: Mapping[str, Any], fallback: str = "") -> str:
    """Read ``streamSid`` from a start or media message."""
    for key in ("streamSid", "stream_sid", "streamId"):
        if message.get(key):
            return str(message[key]).strip()
    start = message.get("start")
    if isinstance(start, Mapping):
        for key in ("streamSid", "stream_sid", "streamId"):
            if start.get(key):
                return str(start[key]).strip()
    return fallback
