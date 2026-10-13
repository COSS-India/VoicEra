"""VI telephony pipeline sample-rate resolution."""

from __future__ import annotations

from typing import Any

from apps.telephony.pipeline_rate_helpers import (
    pipeline_sample_rate,
    recording_sample_rate,
)
from apps.telephony.rates import PipelineRates
from apps.telephony.registry import register_pipeline_rates

# Must match ``serializers.VI_SAMPLE_RATE`` (keep local to avoid pipecat import).
WIRE_SAMPLE_RATE = 8000


@register_pipeline_rates("vi")
def resolve_vi_pipeline_rates(tts: Any) -> PipelineRates:
    """Registered VI pipeline rates (wire 8 kHz + Silero-capped pipeline)."""
    wire_rate = WIRE_SAMPLE_RATE
    pipeline_rate = pipeline_sample_rate(tts, wire_rate)
    return PipelineRates(
        wire_rate=wire_rate,
        pipeline_rate=pipeline_rate,
        recording_rate=recording_sample_rate(tts, pipeline_rate, wire_rate),
    )
