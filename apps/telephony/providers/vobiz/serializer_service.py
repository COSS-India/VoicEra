"""Vobiz frame serializer registration (requires pipecat).

Imported only by ``load_frame_serializers()`` — not loaded by the API.
"""

from __future__ import annotations

from typing import Any

from apps.telephony.providers.vobiz.serializers import VobizFrameSerializer
from apps.telephony.registry import register_frame_serializer


@register_frame_serializer("vobiz")
def create_frame_serializer(
    *,
    stream_sid: str,
    call_sid: str,
    sample_rate: int = 8000,
    **kwargs: Any,
):
    return VobizFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        params=VobizFrameSerializer.InputParams(
            vobiz_sample_rate=sample_rate,
            sample_rate=sample_rate,
            **kwargs,
        ),
    )
