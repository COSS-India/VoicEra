"""Unit tests for the browser WebSocket frame serializer."""

from __future__ import annotations

import asyncio

from pipecat.frames.frames import (
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
    TextFrame,
    TranscriptionFrame,
)

from apps.runtime.services.pipecat.serializer import BrowserProtobufFrameSerializer


def _serialize(frame) -> str | bytes | None:
    return asyncio.run(BrowserProtobufFrameSerializer().serialize(frame))


def test_audio_is_serialized():
    frame = OutputAudioRawFrame(audio=b"\x00\x01", sample_rate=16000, num_channels=1)
    assert _serialize(frame)


def test_transport_message_is_serialized():
    # RTVI rides on this one — dropping it would cost the client its transcript.
    assert _serialize(OutputTransportMessageFrame(message={"label": "rtvi-ai"}))


def test_kinds_the_browser_client_cannot_decode_are_dropped():
    assert _serialize(TextFrame(text="hello")) is None
    assert (
        _serialize(
            TranscriptionFrame(text="hello", user_id="u1", timestamp="2026-09-16T00:00:00Z")
        )
        is None
    )
    assert _serialize(InterruptionFrame()) is None
