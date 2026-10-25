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
async def test_serialize_sends_full_mulaw_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    """A TTS frame larger than 40 ms must leave as one aligned payload, not the first slice."""
    from pipecat.frames.frames import AudioRawFrame

    mulaw = bytes([0xFF] * 1600)

    async def fake_encode(pcm, *, pcm_rate, resampler):
        del pcm, pcm_rate, resampler
        return mulaw

    monkeypatch.setattr(
        "apps.telephony.providers.go2market.serializers.encode_wire_mulaw",
        fake_encode,
    )
    ser = Go2MarketFrameSerializer(stream_sid="MZ1")
    out = await ser.serialize(
        AudioRawFrame(audio=b"\x00\x00" * 800, sample_rate=8000, num_channels=1)
    )
    assert out is not None
    payload = base64.b64decode(json.loads(str(out))["media"]["payload"])
    assert len(payload) == 1600
    assert len(payload) % 160 == 0
    assert ser._mulaw_out_buffer == bytearray()


@pytest.mark.asyncio
async def test_serialize_splits_above_4000_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipecat.frames.frames import AudioRawFrame

    sent: list[int] = []

    class FakeSocket:
        async def send_text(self, payload: str) -> None:
            sent.append(len(base64.b64decode(json.loads(payload)["media"]["payload"])))

    mulaw = bytes([0x7F] * 4800)

    async def fake_encode(pcm, *, pcm_rate, resampler):
        del pcm, pcm_rate, resampler
        return mulaw

    monkeypatch.setattr(
        "apps.telephony.providers.go2market.serializers.encode_wire_mulaw",
        fake_encode,
    )
    ser = Go2MarketFrameSerializer(stream_sid="MZ1", websocket=FakeSocket())
    out = await ser.serialize(
        AudioRawFrame(audio=b"\x00\x00" * 100, sample_rate=8000, num_channels=1)
    )
    returned = len(base64.b64decode(json.loads(str(out))["media"]["payload"]))
    assert sent == [4000]
    assert returned == 800
    assert ser._mulaw_out_buffer == bytearray()


@pytest.mark.asyncio
async def test_serialize_uses_call_sid_when_stream_sid_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipecat.frames.frames import AudioRawFrame

    async def fake_encode(pcm, *, pcm_rate, resampler):
        del pcm, pcm_rate, resampler
        return bytes([0xFF] * 160)

    monkeypatch.setattr(
        "apps.telephony.providers.go2market.serializers.encode_wire_mulaw",
        fake_encode,
    )
    call_sid = "682295a9-34f1-4251-8699-4bea0ff14d13"
    ser = Go2MarketFrameSerializer(stream_sid="", call_sid=call_sid)
    out = await ser.serialize(
        AudioRawFrame(audio=b"\x00\x00" * 160, sample_rate=8000, num_channels=1)
    )
    assert out is not None
    assert json.loads(str(out))["streamSid"] == call_sid


@pytest.mark.asyncio
async def test_serialize_clear_on_interruption() -> None:
    from pipecat.frames.frames import InterruptionFrame

    ser = Go2MarketFrameSerializer(stream_sid="MZ1")
    out = await ser.serialize(InterruptionFrame())
    assert out is not None
    parsed = json.loads(str(out))
    assert parsed["event"] == "clear"
    assert parsed["streamSid"] == "MZ1"
