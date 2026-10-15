"""VI serializer pacing and Pipecat 1.8.1 frame-propagation contract."""

from __future__ import annotations

import json
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
async def test_aligned_audio_returns_payload_so_pipecat_propagates_downstream() -> None:
    """Pipecat 1.8.1 drops AudioBuffer frames when serialize() returns None.

    Emitting any frame-aligned chunk (even under MIN_CHUNK) keeps write_audio_frame
    successful so bot audio reaches AudioBufferProcessor after transport.output().
    """
    serializer = ViFrameSerializer(room_id="r1", call_id="c1")
    frame_bytes = CHUNK_ALIGN_BYTES  # 10 ms @ 8 kHz — under MIN_CHUNK

    result = await serializer.serialize(
        AudioRawFrame(audio=b"\x00" * frame_bytes, sample_rate=8000, num_channels=1)
    )
    assert result is not None
    message = json.loads(result)
    assert message.get("event") == "media"


@pytest.mark.asyncio
async def test_under_min_chunk_emissions_are_not_serializer_paced() -> None:
    """Successful writes are paced by the transport; serializer only advances clock."""
    serializer = ViFrameSerializer(room_id="r1", call_id="c1")
    frame_bytes = CHUNK_ALIGN_BYTES
    n = (MIN_CHUNK_BYTES // frame_bytes) - 1

    started = time.monotonic()
    for _ in range(n):
        result = await serializer.serialize(
            AudioRawFrame(audio=b"\x00" * frame_bytes, sample_rate=8000, num_channels=1)
        )
        assert result is not None
    elapsed = time.monotonic() - started

    # Must not sleep for ~realtime of n frames (transport owns that sleep).
    assert elapsed < (n * frame_bytes / BYTES_PER_SECOND) * 0.5


@pytest.mark.asyncio
async def test_emitted_min_chunk_is_not_double_paced() -> None:
    serializer = ViFrameSerializer(room_id="r1", call_id="c1")
    pcm = b"\x00" * MIN_CHUNK_BYTES

    started = time.monotonic()
    result = await serializer.serialize(
        AudioRawFrame(audio=pcm, sample_rate=8000, num_channels=1)
    )
    elapsed = time.monotonic() - started

    assert result is not None
    assert elapsed < (len(pcm) / BYTES_PER_SECOND) * 0.5


@pytest.mark.asyncio
async def test_pipeline_rate_audio_is_resampled_and_emitted() -> None:
    """16 kHz pipeline frames produce 8 kHz wire payloads on the first write.

    Outbound uses create_file_resampler() so SOXR stream priming cannot return
    empty and drop MediaSender downstream frames under pipecat-ai==1.8.1.
    """
    serializer = ViFrameSerializer(room_id="r1", call_id="c1")
    # 40 ms @ 16 kHz mono 16-bit (typical transport chunk with default 4×10ms).
    pcm_16k = b"\x00\x00" * int(16000 * 0.04)

    result = await serializer.serialize(
        AudioRawFrame(audio=pcm_16k, sample_rate=16000, num_channels=1)
    )
    assert result is not None
    assert json.loads(result).get("event") == "media"
