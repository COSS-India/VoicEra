"""Plivo frame serializer registration (requires pipecat).

Imported only by ``load_frame_serializers()`` — not loaded by the API.
"""

from __future__ import annotations

from typing import Any

from apps.telephony.registry import register_frame_serializer


@register_frame_serializer("plivo")
def create_frame_serializer(
    *,
    stream_sid: str,
    call_sid: str,
    sample_rate: int = 8000,
    **kwargs: Any,
):
    from pipecat.serializers.plivo import PlivoFrameSerializer

    return PlivoFrameSerializer(
        stream_id=stream_sid,
        call_id=call_sid,
        params=PlivoFrameSerializer.InputParams(
            plivo_sample_rate=sample_rate,
            sample_rate=sample_rate,
            **kwargs,
        ),
    )
