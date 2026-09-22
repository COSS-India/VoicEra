"""VI telephony pipeline sample-rate resolution."""

from __future__ import annotations

from typing import Any

from apps.telephony.rates import PipelineRates
from apps.telephony.registry import register_pipeline_rates

# Must match ``serializers.VI_SAMPLE_RATE`` (keep local to avoid pipecat import).
WIRE_SAMPLE_RATE = 8000

# Silero VAD (via Pipecat VADController) only accepts 8000 or 16000 Hz and is
# wired to pipeline audio_in_sample_rate — pipeline cannot exceed this cap.
SILERO_MAX_SAMPLE_RATE = 16000


def tts_native_sample_rate(tts: Any, fallback: int) -> int:
    """Return the TTS service's native output sample rate.

    Supports a bare TTS service or a switcher with ``.services`` members.
    """
    candidates: list[Any] = [tts]
    services = getattr(tts, "services", None)
    if services:
        candidates.extend(list(services))
    for candidate in candidates:
        init_rate = getattr(candidate, "_init_sample_rate", None)
        if init_rate:
            return int(init_rate)
        rate = int(getattr(candidate, "sample_rate", 0) or 0)
        if rate > 0:
            return rate
    return fallback


def pipeline_sample_rate(tts: Any, wire_rate: int) -> int:
    """Pick a pipeline rate that keeps VAD, STT, TTS, and recording aligned.

    VI media stays at ``wire_rate`` (8 kHz); the serializer resamples at the
    boundary. Inside the pipeline we prefer the TTS native rate when Silero
    allows it, otherwise cap at 16 kHz so Pipecat resamplers handle Orpheus 24 kHz.
    """
    tts_rate = tts_native_sample_rate(tts, wire_rate)
    if tts_rate <= wire_rate:
        return wire_rate
    if tts_rate <= SILERO_MAX_SAMPLE_RATE:
        return tts_rate
    return SILERO_MAX_SAMPLE_RATE


@register_pipeline_rates("vi")
def resolve_vi_pipeline_rates(tts: Any) -> PipelineRates:
    """Registered VI pipeline rates (wire 8 kHz + Silero-capped pipeline)."""
    wire_rate = WIRE_SAMPLE_RATE
    tts_rate = tts_native_sample_rate(tts, wire_rate)
    pipeline_rate = pipeline_sample_rate(tts, wire_rate)
    recording_rate = tts_rate if tts_rate > pipeline_rate else pipeline_rate
    return PipelineRates(
        wire_rate=wire_rate,
        pipeline_rate=pipeline_rate,
        recording_rate=recording_rate,
    )
