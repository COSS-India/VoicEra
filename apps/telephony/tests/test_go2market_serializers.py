"""Tests for Go To Market WebSocket frame serializer."""

from __future__ import annotations

import base64
import json

import pytest

from apps.telephony.providers.go2market.serializers import Go2MarketFrameSerializer
from apps.telephony.providers.go2market.stream_protocol import normalize_start_message


def test_normalize_start_message_merges_stream_sid() -> None:
    raw = {
        "event": "start",
        "streamSid": "MZ-top",
        "start": {"callSid": "CA1", "from": "+91x"},
    }
    out = normalize_start_message(raw)
    assert out["start"]["streamSid"] == "MZ-top"
    assert out["start"]["callSid"] == "CA1"


def test_normalize_start_message_flat_top_level_only() -> None:
    raw = {"event": "start", "streamSid": "MZ-flat", "callSid": "CA-flat"}
    out = normalize_start_message(raw)
    assert out["start"]["streamSid"] == "MZ-flat"
    assert out["start"]["callSid"] == "CA-flat"
    assert out["streamSid"] == "MZ-flat"


@pytest.mark.asyncio
async def test_deserialize_connected_returns_none() -> None:
    ser = Go2MarketFrameSerializer(stream_sid="MZ1")
    assert await ser.deserialize(json.dumps({"event": "connected"})) is None


@pytest.mark.asyncio
async def test_deserialize_media_without_media_key_returns_none() -> None:
    ser = Go2MarketFrameSerializer(stream_sid="MZ1")
    assert await ser.deserialize(json.dumps({"event": "media", "streamSid": "MZ1"})) is None


@pytest.mark.asyncio
async def test_deserialize_media_mulaw() -> None:
    ser = Go2MarketFrameSerializer(
        stream_sid="MZ1",
        params=Go2MarketFrameSerializer.InputParams(pipeline_sample_rate=8000),
    )
    # µ-law silence
    payload = base64.b64encode(bytes([0xFF] * 160)).decode()
    msg = {
        "event": "media",
        "streamSid": "MZ1",
        "media": {"chunk": "1", "timestamp": "100", "payload": payload},
    }
    frame = await ser.deserialize(json.dumps(msg))
    assert frame is not None
    assert len(frame.audio) > 0


@pytest.mark.asyncio
async def test_serialize_clear_on_interruption() -> None:
    from pipecat.frames.frames import InterruptionFrame

    ser = Go2MarketFrameSerializer(stream_sid="MZ1")
    out = await ser.serialize(InterruptionFrame())
    assert out is not None
    parsed = json.loads(str(out))
    assert parsed["event"] == "clear"
    assert parsed["streamSid"] == "MZ1"
