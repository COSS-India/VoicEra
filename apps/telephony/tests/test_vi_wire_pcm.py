"""VI serializer wire PCM: 8 kHz rate, duration, alignment, flush, short utterances."""

from __future__ import annotations

import base64
import json
import struct

import pytest
from pipecat.frames.frames import AudioRawFrame, EndFrame

from apps.telephony.providers.vi.serializers import (
    BYTES_PER_SECOND,
    CHUNK_ALIGN_BYTES,
    MIN_CHUNK_BYTES,
    VI_SAMPLE_RATE,
    ViFrameSerializer,
)


def _pcm16(samples: list[int]) -> bytes:
    return struct.pack("<" + "h" * len(samples), *samples)


def _tone(n_samples: int, amp: int = 1000) -> bytes:
    return _pcm16([amp] * n_samples)


def _decode_media_payloads(messages: list[str]) -> list[bytes]:
    out: list[bytes] = []
    for raw in messages:
        msg = json.loads(raw)
        if msg.get("event") != "media":
            continue
        payload = (msg.get("media") or {}).get("payload") or ""
        out.append(base64.b64decode(payload))
    return out


class _CapturingWebsocket:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def send_text(self, data: str) -> None:
        self.texts.append(data)


async def _feed(
    serializer: ViFrameSerializer,
    *,
    pcm: bytes,
    sample_rate: int,
    frame_samples: int,
) -> list[str]:
    """Serialize PCM in fixed-size frames; return transport payloads (non-None)."""
    payloads: list[str] = []
    samples = memoryview(pcm).cast("h")
    for i in range(0, len(samples), frame_samples):
        chunk = samples[i : i + frame_samples].tobytes()
        result = await serializer.serialize(
            AudioRawFrame(audio=chunk, sample_rate=sample_rate, num_channels=1)
        )
        if result is not None:
            payloads.append(result if isinstance(result, str) else result.decode())
    return payloads


@pytest.mark.asyncio
async def test_8k_known_duration_emits_aligned_pcm_without_speed_change() -> None:
    """0.5 s @ 8 kHz through typical 40 ms MediaSender chunks → ~0.5 s wire PCM."""
    serializer = ViFrameSerializer(room_id="r1", call_id="c1")
    duration_s = 0.5
    n_samples = int(VI_SAMPLE_RATE * duration_s)
    # Distinct ramp so corruption would show up as flat/zeros.
    pcm = _pcm16([(i % 2000) - 1000 for i in range(n_samples)])
    frame_samples = 320  # 40 ms @ 8 kHz

    payloads = await _feed(
        serializer, pcm=pcm, sample_rate=8000, frame_samples=frame_samples
    )
    chunks = _decode_media_payloads(payloads)
    assert chunks
    for c in chunks:
        assert len(c) % CHUNK_ALIGN_BYTES == 0
        assert len(c) >= CHUNK_ALIGN_BYTES

    wire = b"".join(chunks) + bytes(serializer._output_buffer)
    # Early emit may leave a sub-ALIGN tail (<10 ms); duration still ~wall-clock.
    wire_seconds = len(wire) / BYTES_PER_SECOND
    assert wire_seconds == pytest.approx(duration_s, abs=0.02)
    # Not sped up (much shorter) or stretched (much longer).
    assert 0.45 <= wire_seconds <= 0.55
    # Sample values preserved (identity path @ 8 kHz) excluding possible pad on flush.
    assert wire[: len(pcm)] == pcm[: len(wire)]


@pytest.mark.asyncio
async def test_16k_pipeline_resamples_to_8k_with_matching_duration() -> None:
    serializer = ViFrameSerializer(room_id="r1", call_id="c1")
    duration_s = 0.4
    n_in = int(16000 * duration_s)
    pcm = _tone(n_in, amp=1200)
    # 40 ms @ 16 kHz — stock MediaSender chunk size at 16 kHz / 4×10 ms.
    payloads = await _feed(serializer, pcm=pcm, sample_rate=16000, frame_samples=640)
    chunks = _decode_media_payloads(payloads)
    assert chunks
    for c in chunks:
        assert len(c) % CHUNK_ALIGN_BYTES == 0

    wire = b"".join(chunks) + bytes(serializer._output_buffer)
    wire_seconds = len(wire) / BYTES_PER_SECOND
    assert wire_seconds == pytest.approx(duration_s, abs=0.03)
    # Every first serialize at 16 kHz must produce media (file resampler, not stream).
    assert payloads[0] is not None
    assert json.loads(payloads[0]).get("event") == "media"


@pytest.mark.asyncio
async def test_short_utterance_emits_without_waiting_for_min_chunk() -> None:
    """20 ms @ 8 kHz (< MIN_CHUNK) still returns aligned media for propagation."""
    serializer = ViFrameSerializer(room_id="r1", call_id="c1")
    n = int(VI_SAMPLE_RATE * 0.02)  # 160 samples = 320 bytes = 2×ALIGN
    pcm = _tone(n, amp=800)

    result = await serializer.serialize(
        AudioRawFrame(audio=pcm, sample_rate=8000, num_channels=1)
    )
    assert result is not None
    chunks = _decode_media_payloads([result])
    assert len(chunks) == 1
    assert len(chunks[0]) == n * 2
    assert len(chunks[0]) % CHUNK_ALIGN_BYTES == 0
    assert len(chunks[0]) < MIN_CHUNK_BYTES


@pytest.mark.asyncio
async def test_final_flush_force_emits_remainder_and_pads_to_min_chunk() -> None:
    """EndFrame drain sends remaining PCM (force path) then exit."""
    ws = _CapturingWebsocket()
    serializer = ViFrameSerializer(room_id="r1", call_id="c1", websocket=ws)
    # Leave a sub-ALIGN remainder that serialize alone would not emit.
    rem_samples = 40  # 80 bytes < CHUNK_ALIGN_BYTES
    await serializer.serialize(
        AudioRawFrame(audio=_tone(rem_samples), sample_rate=8000, num_channels=1)
    )
    assert len(serializer._output_buffer) == rem_samples * 2

    end = await serializer.serialize(EndFrame())
    assert end is not None
    assert json.loads(end).get("event") == "exit"

    media_oob = [m for m in ws.texts if json.loads(m).get("event") == "media"]
    assert len(media_oob) == 1
    pcm = base64.b64decode(json.loads(media_oob[0])["media"]["payload"])
    # force=True pads to MIN_CHUNK_BYTES with silence.
    assert len(pcm) == MIN_CHUNK_BYTES
    assert len(pcm) % CHUNK_ALIGN_BYTES == 0
    assert serializer._output_buffer == bytearray()


@pytest.mark.asyncio
async def test_sub_align_remainder_is_buffered_not_corrupted() -> None:
    """Bytes below CHUNK_ALIGN stay buffered and prepend the next emission."""
    serializer = ViFrameSerializer(room_id="r1", call_id="c1")
    # 79 samples = 158 bytes < 160 align → None, buffered.
    first = await serializer.serialize(
        AudioRawFrame(audio=_tone(79, amp=500), sample_rate=8000, num_channels=1)
    )
    assert first is None
    assert len(serializer._output_buffer) == 158

    # 1 more sample → 160 bytes → emit exactly one ALIGN frame.
    second = await serializer.serialize(
        AudioRawFrame(audio=_tone(1, amp=500), sample_rate=8000, num_channels=1)
    )
    assert second is not None
    pcm = _decode_media_payloads([second])[0]
    assert len(pcm) == CHUNK_ALIGN_BYTES
    assert serializer._output_buffer == bytearray()
