"""Pipecat 1.8.1 MediaSender: serialize()→None drops downstream frames.

Exercises the real MediaSender write/push path with FastAPIWebsocketOutputTransport
write_audio_frame. WebSocket I/O is mocked; serializer behavior is controlled.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from pipecat.frames.frames import OutputAudioRawFrame
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketCallbacks,
    FastAPIWebsocketClient,
    FastAPIWebsocketOutputTransport,
    FastAPIWebsocketParams,
)


class _ControllableSerializer(FrameSerializer):
    """Returns a caller-supplied payload (or None) from serialize()."""

    def __init__(self) -> None:
        super().__init__()
        self.payload: str | bytes | None = None
        self.serialize_calls = 0

    async def serialize(self, frame) -> str | bytes | None:  # noqa: ANN001
        self.serialize_calls += 1
        return self.payload

    async def deserialize(self, data: str | bytes):  # noqa: ANN001
        return None


def _mock_websocket() -> MagicMock:
    ws = MagicMock()
    ws.send_text = AsyncMock()
    ws.send_bytes = AsyncMock()
    ws.close = AsyncMock()
    # Connected application state for FastAPIWebsocketClient._can_send().
    type(ws).application_state = PropertyMock(
        return_value=MagicMock(name="CONNECTED")
    )
    return ws


def _build_output_transport(
    serializer: FrameSerializer,
) -> tuple[FastAPIWebsocketOutputTransport, list[Any]]:
    """Real FastAPIWebsocketOutputTransport + MediaSender-compatible parent."""
    ws = _mock_websocket()
    callbacks = FastAPIWebsocketCallbacks(
        on_client_connected=AsyncMock(),
        on_client_disconnected=AsyncMock(),
        on_session_timeout=AsyncMock(),
    )
    client = FastAPIWebsocketClient(ws, callbacks)
    # Force connected so write_audio_frame does not bail early.
    type(client).is_connected = property(lambda self: True)  # type: ignore[method-assign]
    type(client).is_closing = property(lambda self: False)  # type: ignore[method-assign]

    params = FastAPIWebsocketParams(
        audio_out_enabled=True,
        audio_out_sample_rate=8000,
        audio_out_channels=1,
        audio_out_10ms_chunks=4,
        serializer=serializer,
        add_wav_header=False,
    )
    parent = MagicMock()
    parent.cleanup = AsyncMock()
    output = FastAPIWebsocketOutputTransport(parent, client, params)
    # Match what setup() would set for 8 kHz / 4×10 ms chunks.
    output._sample_rate = 8000
    output._audio_chunk_size = int(8000 / 100) * 1 * 2 * 4  # 640 bytes
    output._send_interval = 0.0  # skip realtime sleep in tests

    pushed: list[Any] = []

    async def _capture_push(frame, direction=None):  # noqa: ANN001
        pushed.append(frame)

    output.push_frame = _capture_push  # type: ignore[method-assign]
    return output, pushed


@pytest.mark.asyncio
async def test_write_audio_frame_false_when_serialize_returns_none() -> None:
    ser = _ControllableSerializer()
    ser.payload = None
    output, _ = _build_output_transport(ser)
    frame = OutputAudioRawFrame(
        audio=b"\x00\x00" * 320, sample_rate=8000, num_channels=1
    )

    ok = await output.write_audio_frame(frame)

    assert ok is False
    assert ser.serialize_calls == 1


@pytest.mark.asyncio
async def test_write_audio_frame_true_when_serialize_returns_payload() -> None:
    ser = _ControllableSerializer()
    ser.payload = '{"event":"media","media":{"payload":""}}'
    output, _ = _build_output_transport(ser)
    frame = OutputAudioRawFrame(
        audio=b"\x00\x00" * 320, sample_rate=8000, num_channels=1
    )

    ok = await output.write_audio_frame(frame)

    assert ok is True
    assert ser.serialize_calls == 1


@pytest.mark.asyncio
async def test_media_sender_skips_push_downstream_when_write_fails() -> None:
    """Mirrors MediaSender._audio_task_handler: False write ⇒ no push_frame."""
    ser = _ControllableSerializer()
    ser.payload = None
    output, pushed = _build_output_transport(ser)

    params = TransportParams(audio_out_enabled=True, audio_out_sample_rate=8000)
    sender = BaseOutputTransport.MediaSender(
        output,
        destination=None,
        sample_rate=8000,
        audio_chunk_size=640,
        params=params,
    )
    frame = OutputAudioRawFrame(
        audio=b"\x00\x00" * 320, sample_rate=8000, num_channels=1
    )

    # Exact contract from base_output.MediaSender._audio_task_handler (~908–923).
    push_downstream = await sender._internal_write_audio_frame(frame)
    if push_downstream:
        await output.push_frame(frame)

    assert push_downstream is False
    assert pushed == []


@pytest.mark.asyncio
async def test_media_sender_pushes_downstream_when_write_succeeds() -> None:
    ser = _ControllableSerializer()
    ser.payload = '{"event":"media"}'
    output, pushed = _build_output_transport(ser)

    params = TransportParams(audio_out_enabled=True, audio_out_sample_rate=8000)
    sender = BaseOutputTransport.MediaSender(
        output,
        destination=None,
        sample_rate=8000,
        audio_chunk_size=640,
        params=params,
    )
    frame = OutputAudioRawFrame(
        audio=b"\x00\x00" * 320, sample_rate=8000, num_channels=1
    )

    push_downstream = await sender._internal_write_audio_frame(frame)
    if push_downstream:
        await output.push_frame(frame)

    assert push_downstream is True
    assert len(pushed) == 1
    assert pushed[0] is frame
