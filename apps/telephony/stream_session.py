"""WebSocket media stream helpers (provider-agnostic)."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from apps.telephony.providers.go2market.stream_protocol import normalize_start_message

_PREAMBLE_EVENTS = frozenset({"connected"})

# Some carriers (e.g. Vobiz on inbound DID legs) can deliver a few ``media``
# frames before ``start``. Frames are 20 ms, so this allows ~5 s of early audio.
_EARLY_MEDIA_EVENTS = frozenset({"media"})
_DEFAULT_MAX_MESSAGES = 256


async def recv_media_stream_start(
    websocket: Any, *, max_messages: int = _DEFAULT_MAX_MESSAGES
) -> dict[str, Any]:
    """Read JSON WebSocket messages until ``event == start``.

    Ignores preamble events such as ``connected`` (Go To Market / Twilio-style)
    and ``media`` frames that some carriers send before ``start``; that early
    audio is dropped because the pipeline is not running yet.
    Returns the full parsed ``start`` message dict.

    Raises:
        ValueError: On invalid JSON, unexpected end, or missing start.
    """
    early_media = 0
    for _ in range(max_messages):
        raw = await websocket.receive_text()
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid WebSocket JSON: {exc}") from exc

        event = str(data.get("event") or "").strip().lower()
        if event in _EARLY_MEDIA_EVENTS:
            # Don't log each frame's payload; summarise once start arrives.
            early_media += 1
            continue
        # Diagnostic: dump carrier handshake so we can confirm which fields
        # (from/to/direction/streamSid/…) arrive on real inbound legs.
        logger.info(
            "Media stream inbound event={!r} top_keys={} payload={}",
            event,
            sorted(data.keys()),
            json.dumps(data, default=str, ensure_ascii=False),
        )
        if event in _PREAMBLE_EVENTS:
            continue
        if event == "start":
            if early_media:
                logger.warning(
                    "Dropped {} media frame(s) received before start event", early_media
                )
            return normalize_start_message(data)
        raise ValueError(f"Expected start event, got {event!r}")

    raise ValueError("Expected start event before WebSocket message limit")
