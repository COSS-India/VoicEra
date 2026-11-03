"""WebSocket media stream helpers (provider-agnostic)."""

from __future__ import annotations

import json
from typing import Any

from apps.telephony.providers.go2market.stream_protocol import normalize_start_message

_PREAMBLE_EVENTS = frozenset({"connected"})


async def recv_media_stream_start(websocket: Any, *, max_messages: int = 32) -> dict[str, Any]:
    """Read JSON WebSocket messages until ``event == start``.

    Ignores preamble events such as ``connected`` (Go To Market / Twilio-style).
    Returns the full parsed ``start`` message dict.

    Raises:
        ValueError: On invalid JSON, unexpected end, or missing start.
    """
    for _ in range(max_messages):
        raw = await websocket.receive_text()
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid WebSocket JSON: {exc}") from exc

        event = str(data.get("event") or "").strip().lower()
        if event in _PREAMBLE_EVENTS:
            continue
        if event == "start":
            return normalize_start_message(data)
        raise ValueError(f"Expected start event, got {event!r}")

    raise ValueError("Expected start event before WebSocket message limit")
