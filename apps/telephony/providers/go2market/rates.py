"""Go To Market pipeline sample-rate resolution (wire fixed at 8 kHz µ-law)."""

from __future__ import annotations

from typing import Any

from apps.telephony.pipeline_rate_helpers import (
    pipeline_sample_rate,
    recording_sample_rate,
)
from apps.telephony.providers.go2market.wire import WIRE_SAMPLE_RATE
from apps.telephony.rates import PipelineRates
from apps.telephony.registry import register_pipeline_rates


@register_pipeline_rates("go2market")
def resolve_go2market_pipeline_rates(tts: Any) -> PipelineRates:
    wire_rate = WIRE_SAMPLE_RATE
    pipeline_rate = pipeline_sample_rate(tts, wire_rate)
    return PipelineRates(
        wire_rate=wire_rate,
        pipeline_rate=pipeline_rate,
        recording_rate=recording_sample_rate(tts, pipeline_rate, wire_rate),
    )
