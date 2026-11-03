"""Go To Market wire audio transcoding (requires pipecat — runtime serializer only)."""

from __future__ import annotations

from typing import Optional

from pipecat.audio.resamplers.base_audio_resampler import BaseAudioResampler
from pipecat.audio.utils import pcm_to_ulaw, ulaw_to_pcm

from apps.telephony.providers.go2market.wire import WIRE_SAMPLE_RATE

__all__ = [
    "WIRE_SAMPLE_RATE",
    "decode_wire_mulaw",
    "encode_wire_mulaw",
    "expected_mulaw_bytes_for_pcm",
]


def expected_mulaw_bytes_for_pcm(pcm_bytes: int, pcm_rate: int) -> int:
    """µ-law byte count for ``pcm_bytes`` of 16-bit mono PCM after resample to 8 kHz."""
    if pcm_rate <= 0 or pcm_bytes <= 0:
        return 0
    samples = pcm_bytes // 2
    samples_8k = samples * WIRE_SAMPLE_RATE // pcm_rate
    return max(samples_8k, 0)


async def decode_wire_mulaw(
    mulaw: bytes,
    *,
    pipeline_rate: int,
    resampler: BaseAudioResampler,
) -> Optional[bytes]:
    """µ-law/8 kHz (wire) → 16-bit PCM at ``pipeline_rate``.

    Uses a **file** resampler (complete TTS/media chunks), not SOXR stream
    resampling — see Pipecat ``create_file_resampler`` vs ``create_stream_resampler``.
    """
    if not mulaw:
        return None
    pcm = await ulaw_to_pcm(mulaw, WIRE_SAMPLE_RATE, pipeline_rate, resampler)
    return pcm if pcm else None


async def encode_wire_mulaw(
    pcm: bytes,
    *,
    pcm_rate: int,
    resampler: BaseAudioResampler,
) -> Optional[bytes]:
    """16-bit PCM at ``pcm_rate`` → µ-law/8 kHz (wire)."""
    if not pcm:
        return None
    mulaw = await pcm_to_ulaw(pcm, pcm_rate, WIRE_SAMPLE_RATE, resampler)
    return mulaw if mulaw else None
