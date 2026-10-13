"""Go To Market frame serializer registration (requires pipecat).

Imported only by ``load_frame_serializers()`` — not loaded by the API.
"""

from __future__ import annotations

from typing import Any

from apps.telephony.providers.go2market.wire import WIRE_SAMPLE_RATE
from apps.telephony.providers.go2market.serializers import Go2MarketFrameSerializer
from apps.telephony.registry import register_frame_serializer


@register_frame_serializer("go2market")
def create_frame_serializer(
    *,
    stream_sid: str,
    call_sid: str,
    sample_rate: int = WIRE_SAMPLE_RATE,
    **kwargs: Any,
):
    del kwargs
    # ``sample_rate`` is the Pipecat pipeline PCM rate; wire µ-law is always 8 kHz.
    return Go2MarketFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        params=Go2MarketFrameSerializer.InputParams(
            pipeline_sample_rate=sample_rate,
        ),
    )
