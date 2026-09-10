"""VI frame serializer registration (requires pipecat).

Imported only by ``load_frame_serializers()`` — not loaded by the API.
"""

from __future__ import annotations

from typing import Any

from apps.telephony.providers.vi.serializers import VI_SAMPLE_RATE, ViFrameSerializer
from apps.telephony.registry import register_frame_serializer


@register_frame_serializer("vi")
def create_frame_serializer(
    *,
    stream_sid: str,
    call_sid: str,
    sample_rate: int = VI_SAMPLE_RATE,
    websocket=None,
    **kwargs: Any,
):
    del kwargs
    return ViFrameSerializer(
        room_id=stream_sid,
        call_id=call_sid,
        websocket=websocket,
        params=ViFrameSerializer.InputParams(sample_rate=VI_SAMPLE_RATE),
    )
