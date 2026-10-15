"""VI serializer must realtime-pace buffered audio (transport skips sleep on None)."""

from __future__ import annotations

import time

import pytest
from pipecat.frames.frames import AudioRawFrame

from apps.telephony.providers.vi.serializers import (
    BYTES_PER_SECOND,
    CHUNK_ALIGN_BYTES,
    MIN_CHUNK_BYTES,
    ViFrameSerializer,
)


@pytest.mark.asyncio
async def test_buffered_audio_is_paced_in_realtime() -> None:
    serializer = ViFrameSerializer(room_id="r1", call_id="c1")
    frame_bytes = CHUNK_ALIGN_BYTES  # 10 ms @ 8 kHz
    # Stay under MIN_CHUNK so every serialize returns None (transport skips sleep).
    n = (MIN_CHUNK_BYTES // frame_bytes) - 1
    # Clock sleeps on frames 2..n (same pattern as Pipecat's send clock).
    expected = (n - 1) * (frame_bytes / BYTES_PER_SECOND)

    started = time.monotonic()
    for _ in range(n):
        result = await serializer.serialize(
            AudioRawFrame(audio=b"\x00" * frame_bytes, sample_rate=8000, num_channels=1)
        )
        assert result is None
    elapsed = time.monotonic() - started

    assert elapsed >= expected * 0.85


@pytest.mark.asyncio
async def test_emitted_chunk_is_not_double_paced() -> None:
    serializer = ViFrameSerializer(room_id="r1", call_id="c1")
    pcm = b"\x00" * MIN_CHUNK_BYTES

    started = time.monotonic()
    result = await serializer.serialize(
        AudioRawFrame(audio=pcm, sample_rate=8000, num_channels=1)
    )
    elapsed = time.monotonic() - started

    assert result is not None
    # Successful write is paced by the transport; serializer must not sleep here.
    assert elapsed < (len(pcm) / BYTES_PER_SECOND) * 0.5
