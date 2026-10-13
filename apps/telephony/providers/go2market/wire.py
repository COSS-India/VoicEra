"""Go To Market wire-format constants (pipecat-free — safe for API ``load_providers``)."""

from __future__ import annotations

# Fixed telephony wire format — G.711 µ-law @ 8 kHz (guide §1, §4.3, §5.1).
WIRE_SAMPLE_RATE = 8000
PCM_SAMPLE_WIDTH = 2  # 16-bit linear PCM inside the Pipecat pipeline

# Guide §1 / §5.1: inbound mulaw aligned to 160 bytes (10 ms @ 8 kHz µ-law).
MULAW_FRAME_BYTES = 160
# Real-time playback cadence (~40 ms @ 8 kHz µ-law) = 320 bytes (guide §1 / partner spec).
MULAW_PREFERRED_SEND_BYTES = 320
MULAW_MAX_SEND_BYTES = 4000

# µ-law silence octet (guide §6.2 sample).
MULAW_SILENCE_BYTE = 0xFF


def align_mulaw_buffer(size: int, *, unit: int = MULAW_FRAME_BYTES) -> int:
    if size <= 0:
        return 0
    return size - (size % unit)


def pad_mulaw_to_frame(mulaw: bytes) -> bytes:
    """Pad trailing bytes with silence to the next 160-byte boundary."""
    if not mulaw:
        return mulaw
    rem = len(mulaw) % MULAW_FRAME_BYTES
    if rem == 0:
        return mulaw
    return mulaw + bytes([MULAW_SILENCE_BYTE]) * (MULAW_FRAME_BYTES - rem)


def pcm_duration_ms(pcm_bytes: bytes, sample_rate: int) -> float:
    if sample_rate <= 0 or not pcm_bytes:
        return 0.0
    samples = len(pcm_bytes) // PCM_SAMPLE_WIDTH
    return (samples / sample_rate) * 1000.0


def mulaw_duration_ms(mulaw_bytes: bytes) -> float:
    if not mulaw_bytes:
        return 0.0
    return (len(mulaw_bytes) / WIRE_SAMPLE_RATE) * 1000.0
