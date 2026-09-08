"""Telephony frame serializer factory (requires pipecat).

Voice runtime should import from here only::

    from apps.telephony.serializers import create_frame_serializer

    serializer = create_frame_serializer(
        "vobiz",
        stream_sid=stream_sid,
        call_sid=call_sid,
        sample_rate=8000,
    )
"""

from __future__ import annotations

from typing import Any

from apps.telephony.registry import get_frame_serializer_factory

__all__ = ["create_frame_serializer"]


def create_frame_serializer(
    provider: str,
    *,
    stream_sid: str,
    call_sid: str,
    sample_rate: int = 8000,
    **kwargs: Any,
):
    """Build a telephony WebSocket frame serializer for ``provider``.

    Args:
        provider: Registered telephony provider id (case-insensitive).
        stream_sid: Provider media stream identifier.
        call_sid: Provider call identifier.
        sample_rate: Audio sample rate for the serializer.
        **kwargs: Reserved for provider-specific options (currently unused).

    Raises:
        ValueError: When ``provider`` is not supported.
    """
    factory = get_frame_serializer_factory(provider)
    return factory(
        stream_sid=stream_sid,
        call_sid=call_sid,
        sample_rate=sample_rate,
        **kwargs,
    )
