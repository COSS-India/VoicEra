"""Shared telephony pipeline sample-rate resolution (no pipecat import).

Pipecat telephony runs STT/TTS/VAD at ``pipeline_rate`` while some carriers
keep media on the wire at ``wire_rate``. TTS may natively output higher rates
(e.g. 24 kHz); Silero VAD in the pipeline accepts 8000 or 16000 Hz only, so
``pipeline_sample_rate`` caps the internal rate and Pipecat resamplers bridge
TTS ↔ pipeline ↔ serializer wire encode.
"""

from __future__ import annotations

from typing import Any

# Silero VAD (Pipecat VADController) accepts 8000 or 16000 Hz on pipeline input.
SILERO_MAX_SAMPLE_RATE = 16000


def tts_candidates(tts: Any) -> list[Any]:
    candidates: list[Any] = [tts]
    services = getattr(tts, "services", None)
    if services:
        candidates.extend(list(services))
    return candidates


def tts_native_sample_rate(tts: Any, fallback: int) -> int:
    """Native output rate of the configured TTS (service or switcher member)."""
    for candidate in tts_candidates(tts):
        init_rate = getattr(candidate, "_init_sample_rate", None)
        if init_rate:
            return int(init_rate)
        rate = int(getattr(candidate, "sample_rate", 0) or 0)
        if rate > 0:
            return rate
    return fallback


def pipeline_sample_rate(
    tts: Any,
    wire_rate: int,
    *,
    silero_max: int = SILERO_MAX_SAMPLE_RATE,
) -> int:
    """Internal PCM rate for Pipecat; wire encoding stays at ``wire_rate``."""
    tts_rate = tts_native_sample_rate(tts, wire_rate)
    if tts_rate <= wire_rate:
        return wire_rate
    if tts_rate <= silero_max:
        return tts_rate
    return silero_max


def recording_sample_rate(tts: Any, pipeline_rate: int, wire_rate: int) -> int:
    """WAV recording rate: preserve TTS native when above pipeline."""
    tts_rate = tts_native_sample_rate(tts, wire_rate)
    return tts_rate if tts_rate > pipeline_rate else pipeline_rate
