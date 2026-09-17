"""VI WebSocket start-event parsing (no runtime dependencies)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

VI_START_TIMEOUT_SECS = 15.0
VI_START_MAX_MESSAGES = 20


async def read_vi_start_message(websocket: Any) -> tuple[dict[str, Any], str, str]:
    """Read VI WebSocket messages until the start event is received."""
    for _ in range(VI_START_MAX_MESSAGES):
        message = await asyncio.wait_for(
            websocket.receive_text(), timeout=VI_START_TIMEOUT_SECS
        )
        data = json.loads(message)
        event = data.get("event")
        if event == "connected":
            continue
        if event == "start":
            start_info = data.get("start", {}) or {}
            call_sid = (
                start_info.get("call_id")
                or data.get("call_id")
                or start_info.get("callSid")
                or "unknown"
            )
            stream_sid = (
                data.get("room_id")
                or start_info.get("room_id")
                or start_info.get("streamSid")
                or "unknown"
            )
            return data, str(call_sid), str(stream_sid)
    raise TimeoutError("VI start event not received")


def dni_lookup_candidates(start_info: dict[str, Any]) -> list[str]:
    """Phone values from a VI start event to try for agent-by-phone lookup."""
    candidates: list[str] = []
    for field in ("dni", "DNI", "cli", "CLI"):
        raw = start_info.get(field)
        if raw:
            value = str(raw).strip()
            if value and value not in candidates:
                candidates.append(value)
    return candidates
