"""Tests for WebSocket media stream preamble handling."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from apps.telephony.stream_session import recv_media_stream_start


@pytest.mark.asyncio
async def test_recv_media_stream_start_skips_connected() -> None:
    ws = AsyncMock()
    ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps({"event": "connected"}),
            json.dumps(
                {
                    "event": "start",
                    "start": {"callSid": "CA1", "streamSid": "MZ1"},
                }
            ),
        ]
    )
    data = await recv_media_stream_start(ws)
    assert data["event"] == "start"
    assert data["start"]["callSid"] == "CA1"


@pytest.mark.asyncio
async def test_recv_media_stream_start_normalizes_stream_sid() -> None:
    ws = AsyncMock()
    ws.receive_text = AsyncMock(
        return_value=json.dumps(
            {
                "event": "start",
                "streamSid": "MZ-top",
                "start": {"callSid": "CA1"},
            }
        )
    )
    data = await recv_media_stream_start(ws)
    assert data["start"]["streamSid"] == "MZ-top"


@pytest.mark.asyncio
async def test_recv_media_stream_start_direct() -> None:
    ws = AsyncMock()
    ws.receive_text = AsyncMock(
        return_value=json.dumps({"event": "start", "start": {}})
    )
    data = await recv_media_stream_start(ws)
    assert data["event"] == "start"


@pytest.mark.asyncio
async def test_recv_media_stream_start_flat_top_level_stream_sid() -> None:
    ws = AsyncMock()
    ws.receive_text = AsyncMock(
        return_value=json.dumps(
            {"event": "start", "streamSid": "MZ-flat", "callSid": "CA1"}
        )
    )
    data = await recv_media_stream_start(ws)
    assert data["start"]["streamSid"] == "MZ-flat"


@pytest.mark.asyncio
async def test_recv_media_stream_start_rejects_unknown() -> None:
    ws = AsyncMock()
    ws.receive_text = AsyncMock(return_value=json.dumps({"event": "media"}))
    with pytest.raises(ValueError, match="Expected start"):
        await recv_media_stream_start(ws)
